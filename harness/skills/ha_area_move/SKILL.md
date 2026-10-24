# Skill: Home Assistant Entity Area Relocation

Use this skill when moving a Home Assistant device or entity from one area to another.

## Context & Prerequisites
- Home Assistant Core running on localhost with websocket access.
- Tool: `run_command` with `tools/ha_entity_area.py` or MCP tool `homeassistant_mcp`.

## Procedure
1. **List / Verify Entity**:
   First query the entity to verify its exact ID and current area:
   ```bash
   python tools/ha_entity_area.py list <entity_id>
   ```
   *Do not guess entity IDs* (e.g. `light.lamp`). If ambiguous, query `tools/ha_entity_area.py search <keyword>` first.

2. **Move Entity to Target Area**:
   Move the entity using the verified area identifier:
   ```bash
   python tools/ha_entity_area.py move <entity_id> "<target_area>"
   ```

3. **Verify State**:
   Confirm the entity's area attribute has updated:
   ```bash
   python tools/ha_entity_area.py verify <entity_id>
   ```
