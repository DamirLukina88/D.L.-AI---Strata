#!/usr/bin/env python3
"""cad_materials_mcp.py - Free CAD (STEP/IGES/OpenCascade) & Material Science (AFLOW/Materials) MCP server."""
import sys
import json
import urllib.request
import urllib.parse

def lookup_cad_format(format_name: str) -> str:
    f = format_name.lower().strip()
    specs = {
        "step": (
            "## STEP (Standard for the Exchange of Product model data - ISO 10303)\n"
            "- **Type:** Exact B-Rep (Boundary Representation) solid geometry, topology, and assemblies.\n"
            "- **Common Application Protocols:** AP203 (Configuration Controlled 3D Designs), AP214 (Automotive Mechanical Design with colors/layers), AP242 (Managed Model-Based 3D Engineering - modern default with PMI/GD&T).\n"
            "- **OpenCascade Handling:** Parsed via `STEPControl_Reader` / written via `STEPControl_Writer`. Produces exact `TopoDS_Shape` compound/solid hierarchies without polygonal tessellation.\n"
            "- **Format Structure:** Header section followed by `DATA;` section with entity definitions (`#123 = CARTESIAN_POINT('', (0., 0., 0.));`)."
        ),
        "iges": (
            "## IGES (Initial Graphics Exchange Specification - ANSI Y14.26M)\n"
            "- **Type:** Legacy CAD neutral interchange format (surfaces and wireframes).\n"
            "- **Entity Types:** 128 (Rational B-Spline Surface), 142 (Curve on a Parametric Surface), 144 (Trimmed Parametric Surface), 186 (Manifold Solid B-Rep Object).\n"
            "- **Drawbacks:** Often loses manifold watertight solid topology during export compared to STEP AP242.\n"
            "- **OpenCascade Handling:** Parsed via `IGESControl_Reader`."
        ),
        "brep": (
            "## OpenCascade BRep Format (.brep)\n"
            "- **Type:** Native boundary representation structure of the OpenCASCADE Technology (OCCT) geometric modeling kernel.\n"
            "- **Topology Levels:** `TopAbs_COMPOUND`, `COMPSOLID`, `SOLID`, `SHELL`, `FACE`, `WIRE`, `EDGE`, `VERTEX`.\n"
            "- **Geometry:** Points, curves (B-splines, Bezier, analytical), and surfaces (planes, cylinders, tori, BSpline surfaces)."
        )
    }
    for k, v in specs.items():
        if k in f:
            return v
    return f"Specification for '{format_name}' not found. Standard references: STEP (ISO 10303-21/242), IGES 5.3, OpenCascade BRep."

def query_aflow_materials(formula: str) -> str:
    try:
        # Query AFLOW public REST API
        encoded = urllib.parse.quote(formula.strip())
        url = f"https://aflowlib.duke.edu/AFLOWDATA/LIB3_RAW/{encoded}/"
        # Search public AFLOW material property endpoint
        api_url = f"https://aflowlib.duke.edu/search/API/?species({encoded}),$catalog,compound,density,energy_cell,Bravais_lattice_orig?format=json"
        req = urllib.request.Request(api_url, headers={"User-Agent": "DL-AI-Strata/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        
        if not data:
            return f"No crystal structures or material properties found on AFLOW for: {formula}"
        
        lines = [f"## AFLOW Material Science Data: {formula.upper()}\n"]
        for entry in data[:3]:
            comp = entry.get("compound", formula)
            density = entry.get("density", "N/A")
            lattice = entry.get("Bravais_lattice_orig", "N/A")
            energy = entry.get("energy_cell", "N/A")
            lines.append(f"- **Compound:** {comp}\n  • Density: {density} g/cm³\n  • Bravais Lattice: {lattice}\n  • Ground State Energy: {energy} eV/cell\n")
        lines.append(f"**AFLOW Consortium:** https://aflow.org")
        return "\n".join(lines)
    except Exception as e:
        return f"AFLOW material query error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "cad-materials-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "cad_spec_lookup",
                    "description": "Look up STEP AP203/AP214/AP242, IGES, and OpenCascade B-Rep 3D CAD format specifications.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "format": {"type": "string", "description": "Format name: STEP, IGES, or BREP"}
                        },
                        "required": ["format"]
                    }
                },
                {
                    "name": "material_science_lookup",
                    "description": "Look up crystal structures, ground-state energies, and material densities from AFLOW material science database.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "formula": {"type": "string", "description": "Chemical composition or alloy formula, e.g. TiAl, Fe2O3, NiTi"}
                        },
                        "required": ["formula"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "cad_spec_lookup":
                text = lookup_cad_format(args.get("format", ""))
            elif name == "material_science_lookup":
                text = query_aflow_materials(args.get("formula", ""))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
