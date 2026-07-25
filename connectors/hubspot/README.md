# Connect HubSpot

The simplest current setup uses a HubSpot Service Key. Service Keys are designed for system-to-system data integrations such as Settra and do not require an OAuth flow or a developer project.

You need:

- Super Admin access or the **Developer tools access** permission in HubSpot.
- About three minutes.

## 1. Create a Service Key

In HubSpot:

1. Open **Development**.
2. In the left sidebar, open **Keys**, then **Service keys**.
3. Click **Create service key**.
4. Give it a descriptive name, such as `Settra read-only`.

Depending on your account navigation, you might also find Service Keys under **Settings → Integrations → Service Keys**.

## 2. Add read scopes

Click **Add new scope** and add only the data Settra should be able to query.

For the standard CRM connection, use:

| Data      | HubSpot scope                |
| --------- | ---------------------------- |
| Contacts  | `crm.objects.contacts.read`  |
| Companies | `crm.objects.companies.read` |
| Deals     | `crm.objects.deals.read`     |
| Owners    | `crm.objects.owners.read`    |
| Tickets   | `tickets`                    |

`crm.objects.contacts.read` is required because Settra uses the Contacts API to validate the key.

If you want Settra to query HubSpot CMS data, also add the applicable scopes:

| Data                             | HubSpot scope      |
| -------------------------------- | ------------------ |
| Blog posts and other CMS content | `content`          |
| Connected domains                | `cms.domains.read` |
| HubDB                            | `hubdb`            |

Some scopes depend on your HubSpot subscription. You do not need write scopes for Settra.

Review the selected scopes, then click **Create** and confirm.

## 3. Copy the key

Open the new Service Key, click **Show**, then **Copy**. It will look similar to:

```text
pat-na1-********-****-****-****-************
```

Keep the key private. Anyone who has it can use every permission you selected.

## 4. Fill in Settra

Create a HubSpot connection and enter:

| Settra field    | What to enter                                  |
| --------------- | ---------------------------------------------- |
| Connection name | Any useful label, such as `HubSpot production` |
| Service Key     | The complete HubSpot Service Key               |

Click **Save connection**.

## Troubleshooting

**Missing `crm.objects.contacts.read`**

Edit the Service Key in HubSpot, add `crm.objects.contacts.read`, save the change, and retry the connection.

**Contacts work but another data type is missing**

- Add the matching read scope from the tables above.
- Confirm your HubSpot subscription includes that API.
- Retry or refresh the connection after changing scopes.

**You cannot find or create Service Keys**

- Confirm you are a Super Admin or have **Developer tools access**.
- Service Keys are currently a HubSpot public beta and might not yet be available in every account.
- As a fallback, a legacy private-app access token with the same read scopes also works. Paste that access token into Settra's **Service Key** field.

**The key stopped working**

Open **Development → Keys → Service keys** and confirm the key was not deleted, expired, or rotated. If it was exposed, use **Rotate and expire now**, then update Settra with the replacement key.

## Security

Treat the Service Key like a password. Grant only the scopes Settra needs, never commit the key to Git, and rotate it immediately if it is exposed. HubSpot recommends routine rotation and supports a seven-day grace period for non-emergency rotations.

For more details, see the [HubSpot Service Key documentation](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/account-service-keys), [HubSpot scope reference](https://developers.hubspot.com/docs/apps/legacy-apps/authentication/scopes), and [Steampipe HubSpot plugin documentation](https://hub.steampipe.io/plugins/turbot/hubspot).
