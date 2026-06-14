# WhatsApp Channel (WIP)

This provider targets the WhatsApp Business Cloud API.

Create a Settra messaging config with:

- `access_token`
- `verify_token`
- `phone_number_id`

Webhook URL shape:

```text
https://<your-host>/api/messaging/webhooks/whatsapp/<config_id>
```

Use the same `verify_token` when configuring the webhook in Meta.
