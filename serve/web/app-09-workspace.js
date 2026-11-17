// serve/web/app-09-workspace.js - part of the web app (see app-01-util.js): server workspace and uploads.
// A classic script, loaded in order by index.html; it shares its globals with the others.
"use strict";

// ------------------------------------------------------------------ Server Workspace
let wsFiles = [];
let wsRoot = "";                      // the server's workspace folder, for @path references
let wsLoading = false;
const wsSelected = new Set();         // paths of the files ticked for "Download"

function openWorkspace(open = true) {
  const dlg = $("workspace-dialog");
  if (!dlg) return;
  if (open) {
    if (typeof dlg.showModal === "function") {
      try { dlg.showModal(); } catch (e) { dlg.setAttribute("open", ""); }
    } else {
      dlg.setAttribute("open", "");
    }
    loadWorkspaceFiles();
  } else {
    if (typeof dlg.close === "function") dlg.close();
    else dlg.removeAttribute("open");
  }
}

async function loadWorkspaceFiles() {
  if (wsLoading) return;
  wsLoading = true;
  const list = $("ws-file-list");
  if (list) list.innerHTML = `<tr><td colspan="4" class="muted">Loading workspace files&hellip;</td></tr>`;
  try {
    const r = await fetch("api/workspace/files", { headers: headers() });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    wsFiles = data.files || [];
    wsRoot = data.workspace || "";
    const present = new Set(wsFiles.filter((f) => !f.is_dir).map((f) => f.path));
    for (const p of [...wsSelected]) if (!present.has(p)) wsSelected.delete(p);
    if (data.workspace && $("ws-path")) $("ws-path").textContent = data.workspace;
    renderWorkspaceFiles();
  } catch (err) {
    if (list) list.innerHTML = `<tr><td colspan="4" class="muted">Failed to load workspace files: ${esc(err.message)}</td></tr>`;
    toast("error", "Workspace error", err.message);
  } finally {
    wsLoading = false;
  }
}

const wsExpandedFolders = new Set();

function fmtWsSize(b) {
  if (b == null || isNaN(b)) return "–";
  if (b > 1048576) return `${(b / 1048576).toFixed(1)} MB`;
  if (b > 1024) return `${(b / 1024).toFixed(0)} KB`;
  return `${b} B`;
}

function buildWorkspaceTree(items, query = "") {
  const root = {
    name: "",
    path: "",
    is_dir: true,
    folders: new Map(),
    files: [],
    totalFiles: 0,
    totalSize: 0,
    hasMatches: false
  };

  function getOrCreateFolder(segments) {
    let curr = root;
    let currPath = "";
    for (const seg of segments) {
      currPath = currPath ? `${currPath}/${seg}` : seg;
      if (!curr.folders.has(seg)) {
        curr.folders.set(seg, {
          name: seg,
          path: currPath,
          is_dir: true,
          folders: new Map(),
          files: [],
          totalFiles: 0,
          totalSize: 0,
          hasMatches: false
        });
      }
      curr = curr.folders.get(seg);
    }
    return curr;
  }

  // Ensure explicit directories are registered
  for (const item of items) {
    if (item.is_dir) {
      const parts = item.path.split("/").filter(Boolean);
      getOrCreateFolder(parts);
    }
  }

  // Place files into folders
  for (const item of items) {
    if (item.is_dir) continue;
    const parts = item.path.split("/").filter(Boolean);
    const fileName = parts.pop() || item.name;
    const parentFolder = parts.length > 0 ? getOrCreateFolder(parts) : root;

    const isMatch = !query || item.name.toLowerCase().includes(query) || item.path.toLowerCase().includes(query);
    if (isMatch) {
      parentFolder.files.push({
        ...item,
        name: fileName
      });
    }
  }

  // Compute recursive totals
  function computeTotals(node) {
    let count = node.files.length;
    let size = node.files.reduce((sum, f) => sum + (f.size || 0), 0);
    let matched = node.files.length > 0;

    for (const child of node.folders.values()) {
      computeTotals(child);
      count += child.totalFiles;
      size += child.totalSize;
      if (child.hasMatches || child.totalFiles > 0) {
        matched = true;
      }
    }

    node.totalFiles = count;
    node.totalSize = size;
    node.hasMatches = matched;
  }

  computeTotals(root);
  return root;
}

function renderFolderNode(folder, depth, list, query) {
  if (query && !folder.hasMatches && folder.totalFiles === 0) return;

  const isExpanded = wsExpandedFolders.has(folder.path) || Boolean(query);
  const tr = document.createElement("tr");
  tr.className = `ws-folder-row ${depth > 0 ? "ws-folder-row--nested" : ""}`;
  tr.dataset.expanded = String(isExpanded);
  tr.dataset.path = folder.path;

  const indentPx = 12 + depth * 18;

  tr.innerHTML = `
    <td class="ws-file-name-cell" style="padding-left: ${indentPx}px;">
      <input type="checkbox" class="ws-check" aria-label="Select every file in ${esc(folder.name)}">
      <span class="ws-folder-chevron">${isExpanded ? "▼" : "▶"}</span>
      <span class="ws-file-icon">${icon("folder", "st-icon st-icon--sm")}</span>
      <strong class="ws-file-title" title="${esc(folder.path)}">${esc(folder.name)}/</strong>
      <span class="ws-folder-badge">${folder.totalFiles} item${folder.totalFiles === 1 ? "" : "s"}</span>
    </td>
    <td class="num muted small">${fmtWsSize(folder.totalSize)}</td>
    <td class="muted small">–</td>
    <td class="num ws-actions-cell">
      <button type="button" class="st-btn st-btn--icon ws-action-btn ws-del-btn" title="Delete folder">
        ${icon("trash", "st-icon st-icon--sm")}
      </button>
    </td>
  `;

  tr.querySelector("td").onclick = () => {
    if (wsExpandedFolders.has(folder.path)) {
      wsExpandedFolders.delete(folder.path);
    } else {
      wsExpandedFolders.add(folder.path);
    }
    renderWorkspaceFiles();
  };

  tr.querySelector(".ws-del-btn").onclick = (e) => {
    e.stopPropagation();
    deleteFromWorkspace({ name: folder.name, path: folder.path, is_dir: true });
  };

  // ticking a folder ticks every file inside it (also in its subfolders)
  const inside = folderFilePaths(folder);
  const box = tr.querySelector(".ws-check");
  const ticked = inside.filter((p) => wsSelected.has(p)).length;
  box.checked = inside.length > 0 && ticked === inside.length;
  box.indeterminate = ticked > 0 && ticked < inside.length;
  box.disabled = inside.length === 0;
  box.onclick = (e) => e.stopPropagation();
  box.onchange = () => {
    for (const p of inside) box.checked ? wsSelected.add(p) : wsSelected.delete(p);
    renderWorkspaceFiles();
  };

  list.appendChild(tr);

  if (isExpanded) {
    const subfolders = Array.from(folder.folders.values()).sort((a, b) => a.name.localeCompare(b.name));
    for (const sub of subfolders) {
      renderFolderNode(sub, depth + 1, list, query);
    }

    const files = folder.files.slice().sort((a, b) => a.name.localeCompare(b.name));
    for (const file of files) {
      renderFileRow(file, depth + 1, list);
    }
  }
}

function renderFileRow(f, depth, list) {
  const tr = document.createElement("tr");
  if (depth > 0) tr.className = "ws-child-row";

  const indentPx = 12 + depth * 18 + (depth > 0 ? 18 : 0);

  const tdName = document.createElement("td");
  tdName.className = "ws-file-name-cell";
  tdName.style.paddingLeft = `${indentPx}px`;

  const fileIcon = f.kind === "image" ? "image" : "attach";
  tdName.innerHTML = `
    <input type="checkbox" class="ws-check" aria-label="Select ${esc(f.name)}"${wsSelected.has(f.path) ? " checked" : ""}>
    <span class="ws-file-icon">${icon(fileIcon, "st-icon st-icon--sm")}</span>
    <span class="ws-file-title" title="${esc(f.path)}">${esc(f.name)}</span>
  `;
  tdName.querySelector(".ws-check").onchange = (e) => {
    e.target.checked ? wsSelected.add(f.path) : wsSelected.delete(f.path);
    renderWorkspaceFiles();
  };
  tr.appendChild(tdName);

  const tdSize = document.createElement("td");
  tdSize.className = "num muted small";
  tdSize.textContent = fmtWsSize(f.size);
  tr.appendChild(tdSize);

  const tdDate = document.createElement("td");
  tdDate.className = "muted small";
  const d = new Date(f.mtime * 1000);
  tdDate.textContent = `${d.toLocaleDateString()} ${d.toLocaleTimeString([], {hour: "2-digit", minute:"2-digit"})}`;
  tr.appendChild(tdDate);

  const tdActions = document.createElement("td");
  tdActions.className = "num ws-actions-cell";

  const btnAttach = document.createElement("button");
  btnAttach.type = "button";
  btnAttach.className = "st-btn st-btn--secondary st-btn--sm ws-action-btn";
  btnAttach.title = "Attach this file to chat prompt";
  btnAttach.innerHTML = `${icon("attach", "st-icon st-icon--sm")}<span>Attach</span>`;
  btnAttach.onclick = () => attachFromWorkspace(f);
  tdActions.appendChild(btnAttach);

  const btnDown = document.createElement("button");
  btnDown.type = "button";
  btnDown.className = "st-btn st-btn--icon ws-action-btn";
  btnDown.title = "Download to browser";
  btnDown.innerHTML = icon("download", "st-icon st-icon--sm");
  btnDown.onclick = () => downloadFromWorkspace(f);
  tdActions.appendChild(btnDown);

  const btnDel = document.createElement("button");
  btnDel.type = "button";
  btnDel.className = "st-btn st-btn--icon ws-action-btn ws-del-btn";
  btnDel.title = "Delete from workspace";
  btnDel.innerHTML = icon("trash", "st-icon st-icon--sm");
  btnDel.onclick = () => deleteFromWorkspace(f);
  tdActions.appendChild(btnDel);

  tr.appendChild(tdActions);
  list.appendChild(tr);
}

function renderWorkspaceFiles() {
  const list = $("ws-file-list");
  if (!list) return;
  const query = ($("ws-search") ? $("ws-search").value : "").trim().toLowerCase();

  const tree = buildWorkspaceTree(wsFiles, query);

  const allFileCount = wsFiles.filter(f => !f.is_dir).length;
  if ($("ws-count")) {
    $("ws-count").textContent = `${tree.totalFiles} of ${allFileCount} file${allFileCount === 1 ? "" : "s"}`;
  }

  updateWorkspaceSelection(tree);

  if (tree.totalFiles === 0 && tree.folders.size === 0) {
    list.innerHTML = `<tr><td colspan="4" class="muted">${query ? "No matching files" : "Workspace is empty. Drop files or folders above to upload."}</td></tr>`;
    return;
  }

  list.innerHTML = "";

  // Render top-level folders
  const topFolders = Array.from(tree.folders.values()).sort((a, b) => a.name.localeCompare(b.name));
  for (const folder of topFolders) {
    renderFolderNode(folder, 0, list, query);
  }

  // Render root-level files
  const rootFiles = tree.files.slice().sort((a, b) => a.name.localeCompare(b.name));
  for (const file of rootFiles) {
    renderFileRow(file, 0, list);
  }
}

// "Attach" puts an @path reference in the Code prompt; D.L. CLI reads the file into the prompt (@file references)
function attachFromWorkspace(f) {
  const ref = `@${wsRoot ? `${wsRoot}/` : ""}${f.path}`;
  if (!/^@[A-Za-z0-9_\-./]+$/.test(ref)) {
    toast("warn", "Cannot attach this file", "An @file reference cannot hold spaces or special characters: rename it first.");
    return;
  }
  const ta = $("code-mobile-input");
  ta.value = `${ta.value.replace(/\s*$/, "")}${ta.value.trim() ? " " : ""}${ref} `;
  openWorkspace(false);
  ta.focus();
  toast("success", "Added to the prompt", f.name);
}

async function downloadFromWorkspace(f, quiet = false) {
  try {
    // a single-use link the browser's own download manager fetches: streamed straight to disk, with progress and
    // resume, instead of holding the whole file in page memory (large zips failed on mobile)
    const r = await fetch("api/workspace/download-ticket", {
      method: "POST", headers: headers(true), body: JSON.stringify({ file: f.path }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const { url } = await r.json();
    // in the Android app the link goes straight to the phone's download manager: the WebView's own download path
    // fetched it first and used up the single-use ticket
    if (window.RayAndroid && typeof window.RayAndroid.downloadFile === "function") {
      if (!window.RayAndroid.downloadFile(new URL(url, location.href).href, f.name)) throw new Error("the phone refused it");
      if (!quiet) toast("success", "Download started", f.name);
      return true;
    }
    const a = document.createElement("a");
    a.href = url;
    a.download = f.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    if (!quiet) toast("success", "Download started", f.name);
    return true;
  } catch (err) {
    toast("error", "Download failed", `${f.name}: ${err.message}`);
    return false;
  }
}

// every file path in a folder of the workspace tree, its subfolders included
function folderFilePaths(folder) {
  const out = folder.files.map((f) => f.path);
  for (const sub of folder.folders.values()) out.push(...folderFilePaths(sub));
  return out;
}

// the selection bar ("N selected · Download · Clear") and the header's "select all" (the files the search shows)
function updateWorkspaceSelection(tree) {
  const shown = [...tree.files.map((f) => f.path), ...[...tree.folders.values()].flatMap(folderFilePaths)];
  const all = $("ws-check-all");
  if (all) {
    const ticked = shown.filter((p) => wsSelected.has(p)).length;
    all.checked = shown.length > 0 && ticked === shown.length;
    all.indeterminate = ticked > 0 && ticked < shown.length;
    all.disabled = shown.length === 0;
    all.onchange = () => {
      for (const p of shown) all.checked ? wsSelected.add(p) : wsSelected.delete(p);
      renderWorkspaceFiles();
    };
  }
  const n = wsSelected.size;
  if ($("ws-selbar")) $("ws-selbar").hidden = n === 0;
  if ($("ws-sel-count")) $("ws-sel-count").textContent = `${n} file${n === 1 ? "" : "s"} selected`;
}

// each ticked file downloads on its own (a single-use link each); a short gap between them, or browsers drop clicks
async function downloadSelectedFromWorkspace() {
  const files = wsFiles.filter((f) => !f.is_dir && wsSelected.has(f.path));
  if (!files.length) return;
  let started = 0;
  for (const [i, f] of files.entries()) {
    if (i) await new Promise((r) => setTimeout(r, 400));
    if (await downloadFromWorkspace(f, true)) started++;
  }
  if (started) toast("success", `Downloading ${started} file${started === 1 ? "" : "s"}`, "Each one is saved on its own");
  wsSelected.clear();
  renderWorkspaceFiles();
}
if ($("ws-sel-download")) $("ws-sel-download").onclick = () => downloadSelectedFromWorkspace();
if ($("ws-sel-clear")) $("ws-sel-clear").onclick = () => { wsSelected.clear(); renderWorkspaceFiles(); };

async function deleteFromWorkspace(f) {
  const targetLabel = f.is_dir ? `folder "${f.name}" and all its contents` : `"${f.name}"`;
  if (!confirm(`Delete ${targetLabel} from server workspace?`)) return;
  try {
    const r = await fetch(`api/workspace/delete?file=${encodeURIComponent(f.path)}`, {
      method: "POST",
      headers: headers(true),
      body: JSON.stringify({ file: f.path })
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    if (f.is_dir) {
      for (const p of Array.from(wsExpandedFolders)) {
        if (p === f.path || p.startsWith(`${f.path}/`)) {
          wsExpandedFolders.delete(p);
        }
      }
    }
    toast("success", "Deleted", f.name);
    loadWorkspaceFiles();
  } catch (err) {
    toast("error", "Delete failed", err.message);
  }
}

async function extractFilesFromDataTransfer(dataTransfer) {
  if (!dataTransfer) return [];
  const items = dataTransfer.items;
  if (!items || !items.length) {
    return [...(dataTransfer.files || [])];
  }

  const files = [];
  async function readEntry(entry, path = "") {
    if (entry.isFile) {
      return new Promise((resolve) => {
        entry.file((f) => {
          f.relativePath = path ? `${path}/${f.name}` : f.name;
          files.push(f);
          resolve();
        }, () => resolve());
      });
    } else if (entry.isDirectory) {
      const dirReader = entry.createReader();
      return new Promise((resolve) => {
        function readBatch() {
          dirReader.readEntries(async (entries) => {
            if (!entries.length) {
              resolve();
              return;
            }
            const nextPath = path ? `${path}/${entry.name}` : entry.name;
            for (const sub of entries) {
              await readEntry(sub, nextPath);
            }
            readBatch();
          }, () => resolve());
        }
        readBatch();
      });
    }
  }

  const promises = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (item.webkitGetAsEntry) {
      const entry = item.webkitGetAsEntry();
      if (entry) promises.push(readEntry(entry));
    } else {
      const f = item.getAsFile();
      if (f) files.push(f);
    }
  }
  await Promise.all(promises);
  return files.length ? files : [...(dataTransfer.files || [])];
}

// prefix: a folder for chat attachments ("uploads/"), so pasted and dropped pictures stay out of the project's own
// files (checkpoints, reviews).  Returns the stored paths, in order, for the @refs.
async function uploadFilesToWorkspace(fileList, prefix = "") {
  if (!fileList || !fileList.length) return [];
  let count = 0;
  const stored = [];
  for (const file of fileList) {
    try {
      const uploadPath = prefix + (file.relativePath || file.name);
      toast("info", "Uploading…", uploadPath, 1500);
      const r = await fetch(`api/workspace/upload?file=${encodeURIComponent(uploadPath)}`, {
        method: "POST",
        headers: {
          ...headers(),
          "X-Filename": uploadPath,
          "Content-Type": "application/octet-stream"
        },
        body: file
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      stored.push((await r.json().catch(() => ({}))).path || uploadPath);
      count++;
    } catch (err) {
      toast("error", `Failed to upload ${file.name}`, err.message);
    }
  }
  if (count > 0) {
    toast("success", `Uploaded ${count} file${count === 1 ? "" : "s"} to workspace`, "Saved in server workspace");
    loadWorkspaceFiles();
  }
  return stored;
}

if ($("workspace-btn")) $("workspace-btn").onclick = () => openWorkspace(true);
if ($("code-workspace-btn")) $("code-workspace-btn").onclick = () => openWorkspace(true);
if ($("ws-close-btn")) $("ws-close-btn").onclick = () => openWorkspace(false);
if ($("ws-refresh-btn")) $("ws-refresh-btn").onclick = () => loadWorkspaceFiles();
if ($("ws-search")) $("ws-search").oninput = () => renderWorkspaceFiles();
if ($("ws-file-input")) $("ws-file-input").onchange = () => {
  // a copy: clearing the input below empties its FileList while the uploads still await one file after another
  const files = Array.from($("ws-file-input").files);
  $("ws-file-input").value = "";
  uploadFilesToWorkspace(files);
};

const wsDropzone = $("ws-dropzone");
if (wsDropzone) {
  wsDropzone.addEventListener("click", (e) => {
    if (e.target !== $("ws-file-input") && !e.target.closest("label")) {
      $("ws-file-input").click();
    }
  });
  wsDropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      $("ws-file-input").click();
    }
  });
  wsDropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    wsDropzone.classList.add("ws-dropzone--active");
  });
  wsDropzone.addEventListener("dragleave", () => {
    wsDropzone.classList.remove("ws-dropzone--active");
  });
  wsDropzone.addEventListener("drop", async (e) => {
    e.preventDefault();
    wsDropzone.classList.remove("ws-dropzone--active");
    const files = await extractFilesFromDataTransfer(e.dataTransfer);
    if (files.length) uploadFilesToWorkspace(files);
  });
}

const wsDialog = $("workspace-dialog");
if (wsDialog) {
  wsDialog.addEventListener("dragover", (e) => { e.preventDefault(); });
  wsDialog.addEventListener("drop", async (e) => {
    if (e.target !== wsDropzone && !wsDropzone.contains(e.target)) {
      e.preventDefault();
      const files = await extractFilesFromDataTransfer(e.dataTransfer);
      if (files.length) uploadFilesToWorkspace(files);
    }
  });
  wsDialog.addEventListener("click", (e) => {
    // only a click on the backdrop itself: a synthetic or keyboard click (the dropzone's input.click(), Enter on a
    // button) has clientX = clientY = 0, outside a centred dialog, and closed it
    if (e.target !== wsDialog) return;
    const rect = wsDialog.getBoundingClientRect();
    const isInDialog = (rect.top <= e.clientY && e.clientY <= rect.top + rect.height
      && rect.left <= e.clientX && e.clientX <= rect.left + rect.width);
    if (!isInDialog) openWorkspace(false);
  });
}

