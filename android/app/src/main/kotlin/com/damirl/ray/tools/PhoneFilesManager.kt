package com.damirl.ray.tools

import android.content.Context
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.util.Log
import com.damirl.ray.network.NetworkClient
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Full shared phone storage manager (`phone_files`) for Xiaomi 17 Ultra (`/storage/emulated/0`).
 *
 * Actions:
 * - `list`: List files and folders in `/sdcard/<path>` (e.g. "Download", "Documents", "DCIM/Camera", "").
 * - `search`: Search `/sdcard/<path>` for files matching `pattern`.
 * - `pull`: Upload a file from phone storage into the PC workspace (`phone-files/<name>`).
 * - `push`: Download a file from the PC workspace (`workspace_path`) onto the phone (`/sdcard/Download/`).
 * - `read_text`: Read UTF-8 text file from phone storage.
 * - `write_text`: Write UTF-8 text file to phone storage.
 */
class PhoneFilesManager(private val context: Context) {

    companion object {
        private const val TAG = "RayPhoneFiles"
        private val OCTET_MEDIA = "application/octet-stream".toMediaType()
        private const val MAX_UPLOAD_BYTES = 64L * 1024L * 1024L // 64 MB per HTTP relay upload
    }

    private fun storageRoot(): File {
        return try {
            Environment.getExternalStorageDirectory()
        } catch (_: Throwable) {
            File("/storage/emulated/0")
        }
    }

    private fun hasAllFilesAccess(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                Environment.isExternalStorageManager()
            } catch (_: Throwable) {
                true
            }
        } else {
            true
        }
    }

    private fun resolvePhonePath(rawPath: String, defaultDir: String = ""): File? {
        val root = storageRoot().canonicalFile
        val trimmed = rawPath.trim()
            .removePrefix("/sdcard/")
            .removePrefix("sdcard/")
            .removePrefix("/storage/emulated/0/")
            .removePrefix("storage/emulated/0/")
            .trimStart('/')
        val rel = trimmed.ifEmpty { defaultDir }
        val target = if (rel.isEmpty()) root else File(root, rel)
        val canon = try {
            target.canonicalFile
        } catch (_: Throwable) {
            return null
        }
        return if (canon.path == root.path || canon.path.startsWith(root.path + File.separator)) canon else null
    }

    fun execute(
        action: String = "list",
        path: String = "Download",
        workspacePath: String = "",
        pattern: String = "",
        content: String = ""
    ): String {
        val act = action.trim().lowercase(Locale.US)
        if (!hasAllFilesAccess()) {
            Log.w(TAG, "MANAGE_EXTERNAL_STORAGE not yet granted; attempting operation anyway")
        }

        return when (act) {
            "list", "ls", "dir" -> listDirectory(path)
            "search", "find" -> searchFiles(path, pattern.ifEmpty { workspacePath })
            "pull", "upload", "to_pc" -> pullToWorkspace(path, workspacePath)
            "push", "download", "to_phone" -> pushFromWorkspace(workspacePath.ifEmpty { path }, path)
            "read_text", "read", "cat" -> readTextFile(path)
            "write_text", "write" -> writeTextFile(path, content)
            else -> "Error: Unknown phone_files action '$action'. Use 'list', 'search', 'pull', 'push', 'read_text', or 'write_text'."
        }
    }

    private fun listDirectory(rawPath: String): String {
        val dir = resolvePhonePath(rawPath, defaultDir = "")
            ?: return "Error: Invalid phone storage path '$rawPath'."
        if (!dir.exists()) {
            return "Error: Phone path '${relativeDisplay(dir)}' does not exist."
        }
        if (dir.isFile) {
            return "Phone file: ${relativeDisplay(dir)} (${formatSize(dir.length())}, modified ${formatTime(dir.lastModified())})"
        }
        val children = dir.listFiles()?.toList()
            ?: return "Error: Could not list '${relativeDisplay(dir)}'. Ensure All Files Access (MANAGE_EXTERNAL_STORAGE) is enabled."

        if (children.isEmpty()) {
            return "Phone folder '${relativeDisplay(dir)}' is empty."
        }

        val sorted = children.sortedWith(
            compareBy<File> { !it.isDirectory }.thenByDescending { it.lastModified() }
        )
        val sb = StringBuilder()
        sb.append("Phone storage '${relativeDisplay(dir)}' (${children.size} items):\n")
        for (f in sorted.take(60)) {
            if (f.isDirectory) {
                val count = f.list()?.size ?: 0
                sb.append("  [DIR]  %-36s (%d items, %s)\n".format(Locale.US, f.name + "/", count, formatTime(f.lastModified())))
            } else {
                sb.append("  [FILE] %-36s (%8s, %s)\n".format(Locale.US, f.name, formatSize(f.length()), formatTime(f.lastModified())))
            }
        }
        if (children.size > 60) {
            sb.append("  ... and ${children.size - 60} more items.\n")
        }
        return sb.toString().trimEnd()
    }

    private fun searchFiles(rawPath: String, query: String): String {
        val q = query.trim().lowercase(Locale.US)
        if (q.isEmpty()) return "Error: 'pattern' is required for action='search'."
        val startDir = resolvePhonePath(rawPath.ifEmpty { "" }, defaultDir = "")
            ?: return "Error: Invalid search path '$rawPath'."
        if (!startDir.exists()) return "Error: Phone path '${relativeDisplay(startDir)}' does not exist."

        val matches = mutableListOf<File>()
        val queue = ArrayDeque<Pair<File, Int>>()
        queue.add(startDir to 0)
        var visited = 0

        while (queue.isNotEmpty() && matches.size < 50 && visited < 5000) {
            val (curr, depth) = queue.removeFirst()
            visited++
            val list = curr.listFiles() ?: continue
            for (item in list) {
                if (item.name.startsWith(".")) continue
                if (depth == 0 && item.name == "Android") continue // skip sandboxed app cache tree unless asked
                if (item.name.lowercase(Locale.US).contains(q)) {
                    matches.add(item)
                    if (matches.size >= 50) break
                }
                if (item.isDirectory && depth < 5) {
                    queue.add(item to (depth + 1))
                }
            }
        }

        if (matches.isEmpty()) {
            return "No files matching '$query' found under '${relativeDisplay(startDir)}'."
        }
        val sb = StringBuilder("Found ${matches.size} match(es) for '$query' on phone:\n")
        for (m in matches) {
            val kind = if (m.isDirectory) "[DIR] " else "[FILE]"
            val info = if (m.isDirectory) "folder" else formatSize(m.length())
            sb.append("  $kind ${relativeDisplay(m)} ($info, ${formatTime(m.lastModified())})\n")
        }
        return sb.toString().trimEnd()
    }

    private fun pullToWorkspace(phonePath: String, workspaceRel: String): String {
        val src = resolvePhonePath(phonePath)
            ?: return "Error: Invalid phone file path '$phonePath'."
        if (!src.exists() || !src.isFile) {
            return "Error: Phone file '${relativeDisplay(src)}' does not exist or is a directory."
        }
        if (src.length() > MAX_UPLOAD_BYTES) {
            return "Error: '${src.name}' is ${formatSize(src.length())} (exceeds 64 MB relay limit)."
        }

        val cleanName = workspaceRel.trim().removePrefix("phone-files/").removePrefix("/").ifEmpty { src.name }
            .replace("..", "_")
        val primaryRel = "phone-files/$cleanName"
        val fallbackRel = "phone-photos/file_${cleanName.replace("/", "_")}"

        val bytes = try {
            src.readBytes()
        } catch (e: Exception) {
            return "Error reading phone file '${relativeDisplay(src)}': ${e.message}"
        }

        val network = NetworkClient.shared
        // 1. Try uploading directly to phone-files/<cleanName>
        try {
            val req = network.newAuthenticatedRequestBuilder(
                "/v1/ray/phone/upload?file=" + URLEncoder.encode(primaryRel, "UTF-8")
            )
                .header("X-Filename", primaryRel)
                .post(bytes.toRequestBody(OCTET_MEDIA))
                .build()
            network.okHttpClient.newCall(req).execute().use { r ->
                if (r.isSuccessful) {
                    return "Pulled '${relativeDisplay(src)}' (${formatSize(bytes.size.toLong())}) to PC workspace as $primaryRel."
                }
            }
        } catch (_: Exception) {
        }

        // 2. Fallback to phone-photos/file_<cleanName> (phone_mcp.py automatically moves it to phone-files/<cleanName>)
        return try {
            val req = network.newAuthenticatedRequestBuilder(
                "/v1/ray/phone/upload?file=" + URLEncoder.encode(fallbackRel, "UTF-8")
            )
                .header("X-Filename", fallbackRel)
                .post(bytes.toRequestBody(OCTET_MEDIA))
                .build()
            network.okHttpClient.newCall(req).execute().use { r ->
                if (!r.isSuccessful) {
                    return "Error uploading file to PC workspace (HTTP ${r.code})."
                }
            }
            "Pulled '${relativeDisplay(src)}' (${formatSize(bytes.size.toLong())}) to PC workspace as $primaryRel (via $fallbackRel)."
        } catch (e: Exception) {
            "Error uploading file to PC workspace: ${e.message}"
        }
    }

    private fun pushFromWorkspace(workspaceRel: String, phoneDestPath: String): String {
        val cleanWs = workspaceRel.trim().removePrefix("/")
        if (cleanWs.isEmpty()) {
            return "Error: 'workspace_path' is required for action='push'."
        }
        val destBase = resolvePhonePath(phoneDestPath.ifEmpty { "Download" }, defaultDir = "Download")
            ?: return "Error: Invalid phone destination path '$phoneDestPath'."

        val fileName = File(cleanWs).name
        val destFile = if (destBase.exists() && destBase.isDirectory) {
            File(destBase, fileName)
        } else if (phoneDestPath.endsWith("/")) {
            File(destBase, fileName)
        } else {
            destBase
        }

        val network = NetworkClient.shared
        val encoded = URLEncoder.encode(cleanWs, "UTF-8")
        val urlsToTry = listOf(
            "/v1/ray/phone/download?file=$encoded",
            "/api/workspace/download?file=$encoded"
        )

        var downloadedBytes: ByteArray? = null
        var lastCode = 0
        for (u in urlsToTry) {
            try {
                val req = network.newAuthenticatedRequestBuilder(u).get().build()
                network.okHttpClient.newCall(req).execute().use { r ->
                    lastCode = r.code
                    if (r.isSuccessful) {
                        downloadedBytes = r.body?.bytes()
                    }
                }
                if (downloadedBytes != null) break
            } catch (_: Exception) {
            }
        }

        val bytes = downloadedBytes
            ?: return "Error: Could not download '$cleanWs' from PC workspace (HTTP $lastCode)."

        return try {
            destFile.parentFile?.mkdirs()
            destFile.writeBytes(bytes)
            try {
                MediaScannerConnection.scanFile(context, arrayOf(destFile.absolutePath), null, null)
            } catch (_: Throwable) {
            }
            "Pushed '$cleanWs' (${formatSize(bytes.size.toLong())}) from PC workspace to phone at '${relativeDisplay(destFile)}'."
        } catch (e: Exception) {
            "Error writing file to phone storage '${relativeDisplay(destFile)}': ${e.message}"
        }
    }

    private fun readTextFile(phonePath: String): String {
        val file = resolvePhonePath(phonePath)
            ?: return "Error: Invalid phone path '$phonePath'."
        if (!file.exists() || !file.isFile) {
            return "Error: Phone file '${relativeDisplay(file)}' does not exist."
        }
        if (file.length() > 512 * 1024) {
            return "Error: '${relativeDisplay(file)}' is ${formatSize(file.length())}; use action='pull' for large files."
        }
        return try {
            val text = file.readText(Charsets.UTF_8)
            "Contents of '${relativeDisplay(file)}' (${formatSize(file.length())}):\n$text"
        } catch (e: Exception) {
            "Error reading '${relativeDisplay(file)}': ${e.message}"
        }
    }

    private fun writeTextFile(phonePath: String, content: String): String {
        val file = resolvePhonePath(phonePath)
            ?: return "Error: Invalid phone path '$phonePath'."
        if (file.isDirectory) {
            return "Error: '${relativeDisplay(file)}' is a directory; specify a file name."
        }
        return try {
            file.parentFile?.mkdirs()
            file.writeText(content, Charsets.UTF_8)
            try {
                MediaScannerConnection.scanFile(context, arrayOf(file.absolutePath), null, null)
            } catch (_: Throwable) {
            }
            "Wrote ${content.toByteArray(Charsets.UTF_8).size} bytes to phone file '${relativeDisplay(file)}'."
        } catch (e: Exception) {
            "Error writing '${relativeDisplay(file)}': ${e.message}"
        }
    }

    private fun relativeDisplay(file: File): String {
        val rootPath = storageRoot().canonicalPath
        val filePath = try { file.canonicalPath } catch (_: Throwable) { file.absolutePath }
        return if (filePath == rootPath) "/sdcard/"
        else if (filePath.startsWith(rootPath + File.separator)) "/sdcard/" + filePath.removePrefix(rootPath + File.separator)
        else filePath
    }

    private fun formatSize(bytes: Long): String = when {
        bytes < 1024L -> "$bytes B"
        bytes < 1024L * 1024L -> "%.1f KB".format(Locale.US, bytes / 1024.0)
        bytes < 1024L * 1024L * 1024L -> "%.2f MB".format(Locale.US, bytes / (1024.0 * 1024.0))
        else -> "%.2f GB".format(Locale.US, bytes / (1024.0 * 1024.0 * 1024.0))
    }

    private fun formatTime(epochMs: Long): String {
        if (epochMs <= 0L) return "unknown"
        return SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US).format(Date(epochMs))
    }
}
