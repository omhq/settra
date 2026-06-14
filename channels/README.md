# Messaging Channels

Messaging channels are conversation entrypoints into Settra. They are separate from
`connectors/`, which describe data sources queried by the agent.

Each channel lives in its own folder:

```text
channels/
  telegram/
    channel.yaml
    README.md
    requirements.txt
    provider.py
```

`channel.yaml` is the machine-readable manifest. `provider.py` implements the
small runtime adapter used by the FastAPI backend.

Provider dependencies should stay local to the channel folder. Production builds
can opt into installing selected channel requirements with the `MESSAGING_CHANNELS`
build argument.

Incoming webhooks are queued in SQLite and acknowledged immediately. The in-app
messaging worker consumes queued jobs, streams the same chat lifecycle used by the
browser UI, sends progress messages such as "Thinking..." or "Running query step",
and then sends the final answer through the channel provider.

## Chat commands

Commands are handled by the shared messaging worker before a message reaches the
LLM, so every provider gets the same behavior:

- `/start` or `/help` shows the command list
- `/new` starts a fresh Settra chat for the current mobile conversation
- `/clear` clears messages from the current Settra chat
- `/delete` deletes the current Settra chat and removes the mobile mapping
