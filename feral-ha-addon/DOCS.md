# FERAL AI Brain — Home Assistant Add-on

## What This Does
Runs the FERAL AI Brain as a Home Assistant add-on. FERAL gets full access to all your Home Assistant devices — lights, switches, sensors, climate, locks, cameras, and 2000+ more device types.

## Setup
1. Add this repository to Home Assistant
2. Install the FERAL Brain add-on
3. Configure your LLM provider (Ollama recommended for local processing)
4. Start the add-on
5. Open the web UI at port 9090

## Configuration
- **llm_provider**: `ollama`, `openai`, `anthropic`, etc.
- **ollama_url**: URL of your Ollama instance (default: `http://homeassistant.local:11434`)
- **openai_api_key**: OpenAI API key (if using OpenAI)
- **anthropic_api_key**: Anthropic API key (if using Anthropic)
