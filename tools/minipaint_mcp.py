#!/usr/bin/env python3
"""minipaint_mcp.py - Miniature Painting, Acrylic Paints Conversion (3,340+ paints), Airbrushing, and Techniques MCP server."""
import sys
import json
import math
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "paints" / "paints.json"
PAINTS = []

def load_paints():
    global PAINTS
    if not PAINTS and DATA_FILE.is_file():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            PAINTS = data.get("paints", [])
        except Exception:
            PAINTS = []

def delta_e(lab1, lab2):
    # Euclidean approximation in Lab space
    return math.sqrt((lab1[0]-lab2[0])**2 + (lab1[1]-lab2[1])**2 + (lab1[2]-lab2[2])**2)

def convert_paint(query: str, target_brand: str = "") -> str:
    load_paints()
    if not PAINTS:
        return "Paint database not loaded. Ensure data/paints/paints.json exists."
    
    q = query.lower().strip()
    match = None
    for p in PAINTS:
        name = p.get("name", "").lower()
        code = (p.get("code") or "").lower()
        pid = p.get("id", "").lower()
        if q == name or q == code or q in pid:
            match = p
            break
    if not match:
        for p in PAINTS:
            if q in p.get("name", "").lower():
                match = p
                break
    
    if not match:
        return f"Paint '{query}' not found in the 3,340-paint database."
    
    source_brand = match.get("brand")
    source_name = match.get("name")
    source_hex = match.get("rgb")
    source_lab = match.get("lab", [50, 0, 0])
    source_range = match.get("range", "")
    
    # Find closest matches
    t_brand = target_brand.lower().strip()
    candidates = []
    for p in PAINTS:
        if p["id"] == match["id"]:
            continue
        if t_brand and t_brand not in p.get("brand", "").lower():
            continue
        dist = delta_e(source_lab, p.get("lab", [50, 0, 0]))
        candidates.append((dist, p))
    
    candidates.sort(key=lambda x: x[0])
    
    lines = [
        f"## Paint Match: {source_brand} - {source_name} ({source_range})",
        f"- **Hex:** `{source_hex}` | **Code:** {match.get('code', 'N/A')}",
        "\n### Closest Equivalent Paints (by ΔE color distance):"
    ]
    for dist, p in candidates[:5]:
        p_brand = p.get("brand")
        p_name = p.get("name")
        p_range = p.get("range")
        p_hex = p.get("rgb")
        d_val = round(dist, 2)
        match_desc = "Exact / Near-identical" if d_val < 2.0 else "Close match" if d_val < 4.5 else "Alternative"
        lines.append(f"- **{p_brand}** ({p_range}) — *{p_name}* (`{p_hex}`) [ΔE: {d_val} - {match_desc}]")
        
    return "\n".join(lines)

AIRBRUSH_RECIPES = {
    "acrylic": {
        "pressure": "18 - 25 PSI",
        "dilution": "1:1 to 1:2 (Paint to Thinner)",
        "medium": "Acrylic Thinner (Vallejo/AK) + 1-2 drops Flow Improver",
        "consistency": "Skim milk consistency; runs down the side of the cup leaving a slight translucent trail.",
        "tip_dry_fix": "Add acrylic retarder or flow improver; periodically wipe needle with damp cotton swab."
    },
    "contrast": {
        "pressure": "15 - 20 PSI",
        "dilution": "Unthinned or 3:1 (Contrast Paint to Contrast Medium)",
        "medium": "Contrast Medium / Speedpaint Medium (never plain water)",
        "consistency": "Naturally liquid; acts as a rich tinted glaze over zenithal / slapchop underpainting.",
        "tip_dry_fix": "Low pressure, light trigger pull to avoid pooling."
    },
    "varnish": {
        "pressure": "22 - 28 PSI",
        "dilution": "2:1 (Varnish to Thinner)",
        "medium": "Airbrush Thinner (never water, which causes clouding/frosting)",
        "consistency": "Slightly thicker than paint; spray in light, misted passes. Avoid heavy wet pooling.",
        "tip_dry_fix": "Clean nozzle immediately with airbrush cleaner after finishing."
    },
    "primer": {
        "pressure": "25 - 30 PSI (0.3mm to 0.5mm nozzle recommended)",
        "dilution": "Unthinned (Vallejo Surface Primer) or 10-20% thinner",
        "medium": "Airbrush Thinner",
        "consistency": "Heavy; needs higher pressure to atomize smoothly without orange peel texture.",
        "tip_dry_fix": "Increase needle size to 0.4mm+ if clogging occurs."
    }
}

def airbrush_guide(paint_type: str = "acrylic") -> str:
    key = paint_type.lower().strip()
    for k, v in AIRBRUSH_RECIPES.items():
        if k in key:
            lines = [f"## Airbrush Technical Parameters: {k.title()} Paints"]
            for prop, val in v.items():
                lines.append(f"- **{prop.replace('_', ' ').title()}:** {val}")
            return "\n".join(lines)
    return "Airbrush guide available for: acrylic, contrast, varnish, primer."

TECHNIQUES = {
    "slapchop": (
        "## Slapchop / Underpainting Technique\n"
        "1. **Prime:** Solid Matte Black (rattle can or airbrush).\n"
        "2. **Heavy Drybrush:** Neutral Grey across all raised angles (45° to 90° down).\n"
        "3. **Light Edge Drybrush:** Pure White on upper edges and top-facing surfaces to establish value contrast.\n"
        "4. **Tint:** Apply single coats of Contrast / Speedpaint / Xpress Color directly over the drybrushing.\n"
        "- **Result:** Shadows, midtones, and highlights emerge automatically from the underpainted values."
    ),
    "glazing": (
        "## Glazing & Layering\n"
        "- **Dilution:** 1 part paint to 4-6 parts water or glaze medium.\n"
        "- **Application:** Wick excess paint onto a paper towel before touching the miniature. The brush should be damp, not dripping.\n"
        "- **Physics:** Stroke in the direction you want the pigment to deposit (pigment accumulates at the end of the brush stroke).\n"
        "- **Drying:** Let each pass dry 100% before applying the next layer to avoid tearing the acrylic skin."
    ),
    "nmm": (
        "## Non-Metallic Metal (NMM)\n"
        "- **Core Principle:** Simulating metal reflections using non-metallic matte pigments (black, dark brown, grey, white, ivory).\n"
        "- **Contrast Rule:** Sharp transitions from deepest shadow to pure white specular bounce light along geometric edges.\n"
        "- **Secondary Reflection:** Add a subtle low-intensity bounce light reflecting the ground/sky on the shadow side."
    ),
    "pin wash": (
        "## Pin Washing & Panel Lining\n"
        "- **Preparation:** Apply a satin or gloss varnish over the miniature first to lower surface tension.\n"
        "- **Application:** Use an oil wash (mineral spirits + artist oil) or enamel wash with a fine #0 brush. Touch the tip to a panel recess; capillary action draws the pigment throughout the line instantly.\n"
        "- **Cleanup:** After 20 minutes, wipe away smudges using a makeup sponge or cotton bud lightly dampened with odorless mineral spirits."
    )
}

def technique_guide(name: str) -> str:
    key = name.lower().strip()
    for k, v in TECHNIQUES.items():
        if k in key or key in k:
            return v
    return f"Technique '{name}' not found. Available: slapchop, glazing, nmm, pin wash."

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "minipaint-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "paint_convert",
                    "description": "Convert miniature acrylic paints across brands (Citadel, Vallejo, AK 3rd Gen, Army Painter, Scale75, Pro Acryl) using CIELAB ΔE color matching.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Paint name, e.g. 'Mephiston Red', 'Ultramarine Blue', 'Corax White', '70.950'"},
                            "target_brand": {"type": "string", "description": "Optional target brand to filter matches: Vallejo, AK, Citadel, Army Painter"}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "airbrush_guide",
                    "description": "Look up airbrush thinning ratios, operating PSI pressures, and troubleshooting for acrylics, contrasts, and varnishes.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "paint_type": {"type": "string", "description": "Paint type: acrylic, contrast, varnish, primer", "default": "acrylic"}
                        }
                    }
                },
                {
                    "name": "technique_guide",
                    "description": "Step-by-step technical guides for miniature painting techniques (slapchop, glazing, NMM, pin washing).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "technique": {"type": "string", "description": "Technique name: slapchop, glazing, nmm, pin wash"}
                        },
                        "required": ["technique"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "paint_convert":
                text = convert_paint(args.get("query", ""), args.get("target_brand", ""))
            elif name == "airbrush_guide":
                text = airbrush_guide(args.get("paint_type", "acrylic"))
            elif name == "technique_guide":
                text = technique_guide(args.get("technique", ""))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
