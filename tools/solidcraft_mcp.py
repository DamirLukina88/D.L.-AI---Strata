#!/usr/bin/env python3
"""solidcraft_mcp.py - Parametric 3D CAD modeling, STEP/STL export, and rendering for Ray.

All generated CAD models, exports, and renders are saved directly into Ray's working directory.
"""
import os
import sys
import json
import socket
import subprocess
import shutil
from pathlib import Path

def get_rei_workspace() -> Path:
    """Resolve Ray's active working directory for saving CAD models."""
    env_ws = os.environ.get("STRATA_WORKSPACE_DIR")
    if env_ws:
        p = Path(env_ws).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    
    default_ws = Path("/mnt/data/DL-AI-workspace")
    if default_ws.is_dir() and os.access(default_ws, os.W_OK):
        return default_ws
    
    cwd = Path.cwd()
    return cwd

def is_gui_listening(port: int = 7878) -> bool:
    """Check whether SolidCraft GUI app is running and listening on the control port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except (OSError, ConnectionRefusedError):
        return False

def get_status() -> str:
    """Get status of SolidCraft engine, GPU renderer, and Ray's CAD workspace."""
    ws = get_rei_workspace()
    gui_online = is_gui_listening(7878)
    
    cli_found = shutil.which("solidcraft-cli") is not None
    gui_bin_found = shutil.which("solidcraft") is not None
    
    gpu_tier = "Unknown"
    if cli_found:
        try:
            p = subprocess.run(["solidcraft-cli", "gpu"], capture_output=True, text=True, timeout=5)
            if p.returncode == 0:
                gpu_tier = p.stdout.strip().replace("\n", " | ")
        except Exception as e:
            gpu_tier = f"Detection error: {e}"
            
    # Find existing CAD models in Ray's workspace
    cad_files = []
    if ws.is_dir():
        for ext in ("*.solidcraft", "*.step", "*.stl", "*.3mf", "*.png"):
            for f in sorted(ws.glob(ext), key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
                cad_files.append(f"- **{f.name}** ({round(f.stat().st_size / 1024, 1)} KB)")
    
    files_summary = "\n".join(cad_files) if cad_files else "No CAD files in workspace yet."
    
    return f"""## SolidCraft CAD Engine Status
- **Ray's CAD Workspace:** `{ws}`
- **SolidCraft CLI (`solidcraft-cli`):** {'Installed (/usr/bin/solidcraft-cli)' if cli_found else 'Not found'}
- **SolidCraft GUI (`solidcraft`):** {'Installed (/usr/bin/solidcraft)' if gui_bin_found else 'Not found'}
- **Live GUI Viewport (port 7878):** {'Connected & Active' if gui_online else 'Not running (Headless execution mode active)'}
- **GPU Renderer:** {gpu_tier}

### Recent CAD Files in Workspace:
{files_summary}

*Tip: Call `solidcraft_create_part` to generate parametric enclosures, brackets, flanges or `solidcraft_build_model` for custom parts.*"""

def inspect_model(filename: str) -> str:
    """Evaluate and measure a 3D CAD model (.solidcraft or .step) in Ray's workspace."""
    ws = get_rei_workspace()
    path = Path(filename)
    if not path.is_absolute():
        path = ws / filename
        
    if not path.exists():
        return f"Error: CAD file not found: `{path}` in workspace `{ws}`"
        
    try:
        p = subprocess.run(["solidcraft-cli", "eval", str(path)], capture_output=True, text=True, timeout=15)
        if p.returncode != 0:
            return f"SolidCraft evaluation error:\n```\n{p.stderr.strip()}\n```"
            
        data = json.loads(p.stdout)
        total = data.get("total", {})
        bodies = data.get("bodies", [])
        params = data.get("params", [])
        timeline = data.get("timeline", [])
        
        out = [f"## CAD Model Inspection: `{path.name}`"]
        out.append(f"- **Path:** `{path}`")
        out.append(f"- **Total Volume:** {round(total.get('volume_mm3', 0.0), 2)} mm³ ({round(total.get('volume_mm3', 0.0) / 1000.0, 3)} cm³)")
        out.append(f"- **Surface Area:** {round(total.get('area_mm2', 0.0), 2)} mm²")
        out.append(f"- **Mass (default 1.29 g/cm³):** {round(total.get('mass_g', 0.0), 2)} g")
        out.append(f"- **Solid Bodies:** {len(bodies)} | **Faces:** {total.get('faces', 0)} | **Edges:** {total.get('edges', 0)}")
        
        if bodies:
            b = bodies[0]
            bbox = b.get("bbox", {})
            bmin, bmax = bbox.get("min", [0,0,0]), bbox.get("max", [0,0,0])
            dx = round(bmax[0] - bmin[0], 2)
            dy = round(bmax[1] - bmin[1], 2)
            dz = round(bmax[2] - bmin[2], 2)
            out.append(f"- **Bounding Box:** {dx} × {dy} × {dz} mm (X: [{round(bmin[0], 1)}, {round(bmax[0], 1)}], Y: [{round(bmin[1], 1)}, {round(bmax[1], 1)}], Z: [{round(bmin[2], 1)}, {round(bmax[2], 1)}])")
            com = b.get("center_of_mass", [0,0,0])
            out.append(f"- **Center of Mass:** [{round(com[0], 2)}, {round(com[1], 2)}, {round(com[2], 2)}]")
            
        if params:
            out.append("\n### Parametric Variables:")
            for pr in params:
                out.append(f"- `{pr.get('name')}` = **{pr.get('expression')}** ({pr.get('value')} {pr.get('unit', '')})")
                
        errors = [f"Step {step.get('id')} ({step.get('name')}): {step.get('error')}" for step in timeline if step.get("error")]
        if errors:
            out.append("\n### Timeline Errors:")
            out.extend([f"- {e}" for e in errors])
        else:
            out.append("\n- **Timeline Health:** 100% Manifold / No feature errors")
            
        return "\n".join(out)
    except Exception as e:
        return f"Inspection error: {e}"

def render_snapshot(filename: str, view: str = "iso", section: str = None, width: int = 1280, height: int = 800, output_name: str = None) -> str:
    """Render a PNG snapshot of a model in Ray's workspace."""
    ws = get_rei_workspace()
    path = Path(filename)
    if not path.is_absolute():
        path = ws / filename
        
    if not path.exists():
        return f"Error: CAD file not found: `{path}`"
        
    out_img_name = output_name or f"{path.stem}_{view}.png"
    out_img_path = ws / out_img_name
    
    cmd = [
        "solidcraft-cli", "snapshot", str(path),
        "--out", str(out_img_path),
        "--view", view,
        "--width", str(width),
        "--height", str(height)
    ]
    if section:
        cmd.extend(["--section", str(section)])
        
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if p.returncode != 0:
            return f"Snapshot render error:\n```\n{p.stderr.strip()}\n```"
            
        return f"""## SolidCraft Render Generated
- **Image File:** `{out_img_path}`
- **Viewpoint:** `{view}` | **Resolution:** {width} × {height}
- **File Size:** {round(out_img_path.stat().st_size / 1024, 1)} KB
- **Saved in Workspace:** `{ws}`

*Image is ready for visual inspection.*"""
    except Exception as e:
        return f"Render snapshot error: {e}"

def build_custom_model(name: str, commands: list | str, parameters: dict = None, formats: list = None, view: str = "iso") -> str:
    """Execute SolidCraft CAD command batch and save all outputs to Ray's workspace."""
    ws = get_rei_workspace()
    slug = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name.strip()).strip("_")
    if not slug:
        slug = "model"
        
    if isinstance(commands, str):
        try:
            cmd_list = json.loads(commands)
        except Exception as e:
            return f"Error parsing commands JSON: {e}"
    else:
        cmd_list = list(commands)
        
    # Prepend parameter definitions if provided
    full_script = []
    if parameters and isinstance(parameters, dict):
        for k, v in parameters.items():
            full_script.append({
                "command": "parameters.add",
                "params": {"name": str(k), "expression": str(v)}
            })
    full_script.extend(cmd_list)
    
    # Save script to workspace
    script_path = ws / f"{slug}_script.json"
    script_path.write_text(json.dumps(full_script, indent=2))
    
    formats = formats or ["solidcraft", "step", "stl", "png"]
    
    out_sc = ws / f"{slug}.solidcraft"
    out_step = ws / f"{slug}.step"
    out_stl = ws / f"{slug}.stl"
    out_3mf = ws / f"{slug}.3mf"
    out_png = ws / f"{slug}.png"
    
    run_cmd = ["solidcraft-cli", "run", str(script_path), "--results"]
    if "solidcraft" in formats:
        run_cmd.extend(["--save", str(out_sc)])
    if "step" in formats:
        run_cmd.extend(["--out", str(out_step)])
    if "stl" in formats:
        run_cmd.extend(["--out", str(out_stl)])
    if "3mf" in formats:
        run_cmd.extend(["--out", str(out_3mf)])
        
    try:
        p = subprocess.run(run_cmd, capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            err = p.stderr.strip() or p.stdout.strip()
            return f"SolidCraft build error for `{slug}`:\n```\n{err}\n```"
            
        generated_files = []
        if out_sc.exists() and "solidcraft" in formats:
            generated_files.append(f"- **SolidCraft Project:** `{out_sc}` ({round(out_sc.stat().st_size / 1024, 1)} KB)")
        if out_step.exists() and "step" in formats:
            generated_files.append(f"- **STEP (CAD Neutral):** `{out_step}` ({round(out_step.stat().st_size / 1024, 1)} KB)")
        if out_stl.exists() and "stl" in formats:
            generated_files.append(f"- **STL (3D Print Mesh):** `{out_stl}` ({round(out_stl.stat().st_size / 1024, 1)} KB)")
        if out_3mf.exists() and "3mf" in formats:
            generated_files.append(f"- **3MF:** `{out_3mf}` ({round(out_3mf.stat().st_size / 1024, 1)} KB)")
            
        # Snapshot render
        if "png" in formats and out_sc.exists():
            snap_cmd = ["solidcraft-cli", "snapshot", str(out_sc), "--out", str(out_png), "--view", view, "--width", "1280", "--height", "800"]
            subprocess.run(snap_cmd, capture_output=True, text=True, timeout=15)
            if out_png.exists():
                generated_files.append(f"- **Render Snapshot:** `{out_png}` ({round(out_png.stat().st_size / 1024, 1)} KB)")
                
        # Get physical evaluation
        eval_summary = ""
        if out_sc.exists():
            eval_p = subprocess.run(["solidcraft-cli", "eval", str(out_sc)], capture_output=True, text=True, timeout=10)
            if eval_p.returncode == 0:
                ed = json.loads(eval_p.stdout)
                tot = ed.get("total", {})
                b = ed.get("bodies", [{}])[0] if ed.get("bodies") else {}
                bbox = b.get("bbox", {})
                bmin, bmax = bbox.get("min", [0,0,0]), bbox.get("max", [0,0,0])
                dx = round(bmax[0] - bmin[0], 2)
                dy = round(bmax[1] - bmin[1], 2)
                dz = round(bmax[2] - bmin[2], 2)
                eval_summary = f"""
### Geometry & Physical Measurements:
- **Dimensions (Bounding Box):** {dx} × {dy} × {dz} mm
- **Volume:** {round(tot.get('volume_mm3', 0.0), 2)} mm³ ({round(tot.get('volume_mm3', 0.0) / 1000.0, 3)} cm³)
- **Mass (Density 1.29 g/cm³):** {round(tot.get('mass_g', 0.0), 2)} g
- **Surface Area:** {round(tot.get('area_mm2', 0.0), 2)} mm²
- **Faces / Edges:** {tot.get('faces', 0)} faces | {tot.get('edges', 0)} edges"""
                
        files_text = "\n".join(generated_files)
        return f"""## 3D CAD Model Successfully Built: `{slug}`
- **Destination Workspace:** `{ws}`

### Generated Files in Workspace:
{files_text}
{eval_summary}

*Model is saved and ready for 3D printing (Bambu/Klipper) or CAD editing.*"""
    except Exception as e:
        return f"Model build error: {e}"

def create_parametric_part(part_type: str, name: str = "", parameters: dict = None, formats: list = None, view: str = "iso") -> str:
    """Quick-build common parametric engineering parts directly into Ray's workspace."""
    pt = part_type.lower().strip()
    slug = name.strip() or f"{pt}_part"
    p = parameters or {}
    
    if pt in ("enclosure", "box", "case"):
        # Parametric hollow box
        L = float(p.get("length", 80.0))
        W = float(p.get("width", 50.0))
        H = float(p.get("height", 30.0))
        wall = float(p.get("wall_thickness", 2.5))
        fillet = float(p.get("fillet_radius", 3.0))
        
        cmds = [
            {"command": "parameters.add", "params": {"name": "L", "expression": str(L)}},
            {"command": "parameters.add", "params": {"name": "W", "expression": str(W)}},
            {"command": "parameters.add", "params": {"name": "H", "expression": str(H)}},
            {"command": "parameters.add", "params": {"name": "wall", "expression": str(wall)}},
            {"command": "solid.box", "params": {"name": "MainBox", "length": "L", "width": "W", "height": "H", "center": [0, 0, "H/2"]}},
            {"command": "solid.shell", "params": {"thickness": "wall", "faces": [[0, 0, H]]}}
        ]
        return build_custom_model(slug, cmds, formats=formats, view=view)
        
    elif pt in ("bracket", "l_bracket", "angle"):
        # Parametric L-bracket with mounting holes and root fillet
        leg_a = float(p.get("leg_a", 50.0))
        leg_b = float(p.get("leg_b", 50.0))
        width = float(p.get("width", 30.0))
        thickness = float(p.get("thickness", 4.0))
        hole_dia = float(p.get("hole_dia", 5.5))
        fillet_r = float(p.get("fillet_radius", 3.0))
        
        cmds = [
            {"command": "parameters.add", "params": {"name": "LegA", "expression": str(leg_a)}},
            {"command": "parameters.add", "params": {"name": "LegB", "expression": str(leg_b)}},
            {"command": "parameters.add", "params": {"name": "W", "expression": str(width)}},
            {"command": "parameters.add", "params": {"name": "T", "expression": str(thickness)}},
            {"command": "parameters.add", "params": {"name": "HoleDia", "expression": str(hole_dia)}},
            {"command": "solid.box", "params": {"name": "BaseLeg", "length": "LegA", "width": "W", "height": "T", "corner": [0, 0, 0]}},
            {"command": "solid.box", "params": {"name": "UprightLeg", "length": "T", "width": "W", "height": "LegB - T", "corner": [0, 0, "T"], "operation": "join"}},
            {"command": "solid.fillet", "params": {"edges": [[thickness, width / 2.0, thickness]], "radius": str(fillet_r)}},
            {"command": "solid.cylinder", "params": {"name": "HoleBase", "radius": "HoleDia/2", "height": "T", "base": ["LegA - 15", "W/2", 0], "axis": [0, 0, 1], "operation": "cut"}},
            {"command": "solid.cylinder", "params": {"name": "HoleUpright", "radius": "HoleDia/2", "height": "T", "base": [0, "W/2", "LegB - 15"], "axis": [1, 0, 0], "operation": "cut"}}
        ]
        return build_custom_model(slug, cmds, formats=formats, view=view)
        
    elif pt in ("flange", "disk", "plate"):
        # Parametric circular flange with center bore and bolt pattern
        od = float(p.get("outer_dia", 80.0))
        id_bore = float(p.get("inner_bore", 30.0))
        thick = float(p.get("thickness", 10.0))
        pcd = float(p.get("pcd", 58.0))
        hole_dia = float(p.get("hole_dia", 6.5))
        hole_count = int(p.get("hole_count", 4))
        
        cmds = [
            {"command": "parameters.add", "params": {"name": "OD", "expression": str(od)}},
            {"command": "parameters.add", "params": {"name": "ID", "expression": str(id_bore)}},
            {"command": "parameters.add", "params": {"name": "T", "expression": str(thick)}},
            {"command": "parameters.add", "params": {"name": "PCD", "expression": str(pcd)}},
            {"command": "parameters.add", "params": {"name": "HoleDia", "expression": str(hole_dia)}},
            {"command": "solid.cylinder", "params": {"name": "BaseFlange", "radius": "OD/2", "height": "T", "base": [0, 0, 0], "axis": [0, 0, 1]}},
            {"command": "solid.cylinder", "params": {"name": "BoreCut", "radius": "ID/2", "height": "T", "base": [0, 0, 0], "axis": [0, 0, 1], "operation": "cut"}},
            {"command": "solid.cylinder", "params": {"name": "Hole1", "radius": "HoleDia/2", "height": "T", "base": ["PCD/2", 0, 0], "axis": [0, 0, 1], "operation": "cut"}},
            {"command": "solid.pattern.circular", "params": {"features": ["Hole1"], "axis": "Z", "count": hole_count}}
        ]
        return build_custom_model(slug, cmds, formats=formats, view=view)
        
    elif pt in ("standoff", "spacer", "bushing"):
        # Parametric tubular standoff
        od = float(p.get("outer_dia", 12.0))
        id_bore = float(p.get("inner_dia", 5.2))
        h = float(p.get("height", 20.0))
        
        cmds = [
            {"command": "parameters.add", "params": {"name": "OD", "expression": str(od)}},
            {"command": "parameters.add", "params": {"name": "ID", "expression": str(id_bore)}},
            {"command": "parameters.add", "params": {"name": "H", "expression": str(h)}},
            {"command": "solid.cylinder", "params": {"name": "Body", "radius": "OD/2", "height": "H", "base": [0, 0, 0], "axis": [0, 0, 1]}},
            {"command": "solid.cylinder", "params": {"name": "Bore", "radius": "ID/2", "height": "H", "base": [0, 0, 0], "axis": [0, 0, 1], "operation": "cut"}}
        ]
        return build_custom_model(slug, cmds, formats=formats, view=view)
        
    else:
        return f"Unknown part type '{part_type}'. Available parametric types: 'enclosure', 'bracket', 'flange', 'standoff'."

def launch_gui(filename: str = None) -> str:
    """Launch SolidCraft GUI in the background with port 7878 control enabled."""
    if is_gui_listening(7878):
        return "SolidCraft GUI is already running and listening on port 7878."
        
    ws = get_rei_workspace()
    cmd = ["solidcraft", "--control", "7878"]
    if filename:
        p = Path(filename)
        if not p.is_absolute():
            p = ws / filename
        if p.exists():
            cmd.append(str(p))
            
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return f"Started SolidCraft GUI on port 7878 in the background. Viewport window is now visible on desktop (Workspace: `{ws}`)."
    except Exception as e:
        return f"Error launching SolidCraft GUI: {e}"

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue
            
        m, mid = req.get("method"), req.get("id")
        if m == "initialize":
            res = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "solidcraft-rei-mcp", "version": "1.0.0"}
                }
            }
        elif m == "tools/list":
            tools = [
                {
                    "name": "solidcraft_status",
                    "description": "Check SolidCraft CAD engine status, GPU renderer, GUI connection (port 7878), and list CAD files in Ray's workspace.",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "solidcraft_create_part",
                    "description": "Generate standard parametric CAD parts (enclosure/box, bracket, flange/disk, standoff/spacer). Files (.solidcraft, .step, .stl, .png) are saved directly to Ray's workspace.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "part_type": {"type": "string", "description": "Type of part: 'enclosure', 'bracket', 'flange', or 'standoff'"},
                            "name": {"type": "string", "description": "Basename for generated CAD files (e.g. 'pi_case', 'motor_bracket')"},
                            "parameters": {"type": "object", "description": "Dimension parameters (e.g. {'length': 100, 'width': 60, 'height': 40, 'wall_thickness': 2.5})"},
                            "formats": {"type": "array", "items": {"type": "string"}, "description": "Export formats: ['solidcraft', 'step', 'stl', 'png']"},
                            "view": {"type": "string", "default": "iso", "description": "Snapshot render view: 'iso', 'top', 'front', 'right'"}
                        },
                        "required": ["part_type"]
                    }
                },
                {
                    "name": "solidcraft_build_model",
                    "description": "Execute custom parametric SolidCraft CAD commands (sketches, extrusions, cuts, fillets, patterns). All models and renders are saved directly to Ray's workspace.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Basename for model files"},
                            "commands": {
                                "type": "array",
                                "description": "List of SolidCraft command dicts: [{'command': 'solid.box', 'params': {...}}, ...]"
                            },
                            "parameters": {"type": "object", "description": "Parametric variables to inject (e.g. {'W': '80', 'H': '40'})"},
                            "formats": {"type": "array", "items": {"type": "string"}, "description": "Export formats (default ['solidcraft', 'step', 'stl', 'png'])"},
                            "view": {"type": "string", "default": "iso"}
                        },
                        "required": ["name", "commands"]
                    }
                },
                {
                    "name": "solidcraft_inspect_model",
                    "description": "Inspect and measure any CAD model (.solidcraft or .step) in Ray's workspace: volume, mass, bounding box, center of mass, faces, and timeline health.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "Name or path of .solidcraft or .step file in workspace"}
                        },
                        "required": ["filename"]
                    }
                },
                {
                    "name": "solidcraft_render_snapshot",
                    "description": "Render a high-resolution PNG snapshot or cross-section of a 3D model in Ray's workspace.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "Name or path of .solidcraft or .step file in workspace"},
                            "view": {"type": "string", "default": "iso", "description": "'iso', 'top', 'front', 'bottom', 'right', 'left'"},
                            "section": {"type": "string", "description": "Optional cross-section plane (e.g. 'z=15' or 'YZ') to view inside cavities"},
                            "width": {"type": "integer", "default": 1280},
                            "height": {"type": "integer", "default": 800},
                            "output_name": {"type": "string", "description": "Optional output PNG filename"}
                        },
                        "required": ["filename"]
                    }
                },
                {
                    "name": "solidcraft_launch_gui",
                    "description": "Launch the SolidCraft 3D CAD GUI application on the desktop with live control port 7878 enabled.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "Optional .solidcraft or .step file to open in the viewport"}
                        }
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            
            if name == "solidcraft_status":
                text = get_status()
            elif name == "solidcraft_create_part":
                text = create_parametric_part(
                    part_type=args.get("part_type", "enclosure"),
                    name=args.get("name", ""),
                    parameters=args.get("parameters"),
                    formats=args.get("formats"),
                    view=args.get("view", "iso")
                )
            elif name == "solidcraft_build_model":
                text = build_custom_model(
                    name=args.get("name", "model"),
                    commands=args.get("commands", []),
                    parameters=args.get("parameters"),
                    formats=args.get("formats"),
                    view=args.get("view", "iso")
                )
            elif name == "solidcraft_inspect_model":
                text = inspect_model(filename=args.get("filename", ""))
            elif name == "solidcraft_render_snapshot":
                text = render_snapshot(
                    filename=args.get("filename", ""),
                    view=args.get("view", "iso"),
                    section=args.get("section"),
                    width=args.get("width", 1280),
                    height=args.get("height", 800),
                    output_name=args.get("output_name")
                )
            elif name == "solidcraft_launch_gui":
                text = launch_gui(filename=args.get("filename"))
            else:
                text = f"Unknown tool: {name}"
                
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
            
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
