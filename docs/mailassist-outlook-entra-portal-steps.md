# MailAssist Outlook Entra App Portal Steps

Use this to create or verify the app registration before the Magali Zoom call.
This does not require access to Magali's mailbox content, but it does require a
Microsoft Entra account that can create app registrations.

## Goal

Create a public/native MailAssist app registration for work/school Microsoft
365 accounts with delegated Graph access to read mail and create drafts. The app
must not be able to send email.

## Portal Steps

1. Open Microsoft Entra admin center:

   `https://entra.microsoft.com/`

2. Go to:

   `Applications` -> `App registrations` -> `New registration`

3. Set:

   - Name: `MailAssist Outlook`
   - Supported account types: `Accounts in any organizational directory`
   - Redirect URI: leave blank for the device-code path

4. Create the app registration.

5. Copy:

   - Application (client) ID
   - Directory (tenant) ID, if this is the Golden Years tenant

6. Open `Authentication`.

7. Under advanced settings, enable public client/native flows:

   - `Allow public client flows`: `Yes`

8. Open `API permissions`.

9. Add Microsoft Graph delegated permissions:

   - `offline_access`
   - `User.Read`
   - `Mail.ReadWrite`

10. Verify there are no application permissions.

11. Verify `Mail.Send` is not present.

12. If the tenant requires admin consent, grant admin consent only for the three
    delegated permissions above.

## Manifest Cross-Check

`docs/mailassist-outlook-entra-app-manifest.json` records the expected core
manifest shape:

- `signInAudience`: `AzureADMultipleOrgs`
- `isFallbackPublicClient`: `true`
- Microsoft Graph delegated scope IDs:
  - `offline_access`: `7427e0e9-2fba-42fe-b0c0-848c9e6a8182`
  - `User.Read`: `e1fe6dd8-ba31-4d61-89e7-88639da4683d`
  - `Mail.ReadWrite`: `024d486e-b451-40bb-833d-3e66d98c5c73`

Do not add the Mail.ReadWrite application permission
`e2a3a72e-5f79-4c64-b1b1-878b674786c9`; MailAssist uses delegated user sign-in.

`docs/mailassist-outlook-graph-permissions.json` is the same Graph permission
set in the array shape expected by Azure CLI's `--required-resource-accesses`
argument.

## Azure CLI Path

Azure CLI is installed on the current Mac workspace. After signing in with an
account that can create app registrations, run:

```bash
az login
./tools/create-outlook-entra-app.sh
```

To also write the resulting client id and current tenant id into the local
ignored `.env`, run:

```bash
./tools/create-outlook-entra-app.sh --write-env
```

To update an existing app registration instead of creating a new one:

```bash
./tools/create-outlook-entra-app.sh --update <application-client-id>
```

To verify an existing app registration before the Zoom call:

```bash
./tools/verify-outlook-entra-app.sh <application-client-id>
```

## Values Needed For The Call

Current verified values:

```text
MAILASSIST_OUTLOOK_CLIENT_ID=2b2639c3-605c-466d-ae89-63ef8ffff5c8
MAILASSIST_OUTLOOK_TENANT_ID=organizations
```

Required:

```text
MAILASSIST_OUTLOOK_CLIENT_ID=<application-client-id>
MAILASSIST_OUTLOOK_TENANT_ID=organizations
```

If the app is created inside the Golden Years tenant, prefer the real tenant id:

```text
MAILASSIST_OUTLOOK_TENANT_ID=<golden-years-tenant-id>
```

## Stop Conditions

Stop and inspect before using the app if:

- Supported account type is personal Microsoft accounts only.
- `Mail.Send` appears anywhere.
- Any application permission appears.
- A client secret is created for this desktop flow.
- The client id is from an unknown app registration.
