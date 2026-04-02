# Adding Skills to ASOS

Extending ASOS relies on mapping Python or JSON boundaries onto LLM function descriptors.

## Defining the Capability (JSON Manifest)

Every capability inside ASOS must be governed by a schema explicitly readable by the Anthropic/OpenAI APIs.

**Create `asos-core/skills/manifests/new_skill.json`:**
```json
{
  "skill_id": "iot_light",
  "requires_daemon": true, 
  "trigger_phrases": ["turn on the light", "make it brighter"],
  "categories": ["iot", "smart_home"],
  "description": "Standardized control for the connected smart bulb.",
  "brand": {
    "name": "Smart Bulb",
    "primary_color": "#f1c40f"
  },
  "endpoints": [
    {
      "id": "set_color",
      "method": "WS_EXECUTE",
      "url": "local_daemon",
      "description": "Sets the RGB color of the light bulb.",
      "params": [
        {
          "name": "rgb_hex",
          "type": "string",
          "description": "The exact hex color excluding the '#', e.g. 'FF0000'.",
          "required": true
        }
      ],
      "ui_hint": "card"
    }
  ]
}
```

The `requires_daemon: true` field explicitly tells the Orchestrator to bypass HTTP routing and instead pack the execution as an `execute` payload directed at a connected WebSocket node.

## Defining the Hardware Code

To handle the incoming payload, modify your daemon code (e.g. `robot_template.py`) to map against the `skill_id` endpoints.

```python
        if executor == "set_color":
            hex_color = args.get("rgb_hex", "FFFFFF")
            # --- Insert GPIO/Serial Code Here ---
            set_bulb_color(hex_color)
            result_msg = f"Bulb changed to {hex_color}"
```

## Defining Pure Python Cloud Skills

If you want the API server to perform the execution (e.g., hitting Stripe or Gmail instead of local hardware):
1. Create a `.py` file inside `asos-core/skills/impl/`.
2. Inherit from `BaseSkill`.
3. Set `requires_daemon: false` in the corresponding manifest.
4. Define the execution override explicitly, handling the exact signature provided by your `endpoints`.

The Orchestrator automatically handles the translation from LLM Tool Calling -> Payload Structuring -> Skill Invocation.
