# Connect Stripe

The simplest setup is to copy a server-side secret key from Stripe and paste it into Settra. Start with a sandbox key so you can verify the connection without touching live payments.

You need:

- Access to your Stripe Dashboard.
- Permission to view API keys.
- About two minutes.

## 1. Choose sandbox or live data

Stripe keeps sandbox and live data separate:

- Use a sandbox key beginning with `sk_test_` while setting up or testing.
- Use a live key beginning with `sk_live_` only when you are ready to query real business data.

If you connect with a sandbox key, Settra will only see sandbox customers, payments, products, and subscriptions.

## 2. Copy the secret key

Open [API keys in the Stripe Dashboard](https://dashboard.stripe.com/apikeys).

For a sandbox:

1. Make sure you are viewing the sandbox you want to connect.
2. Find **Secret key** under **Standard keys**.
3. Click **Reveal test key**.
4. Copy the key beginning with `sk_test_`.

For live data, switch to live mode and copy the live secret key beginning with `sk_live_`. Stripe might show a newly created live key only once, so save it securely before closing the dialog.

Do not copy:

- A publishable key beginning with `pk_`.
- A webhook signing secret beginning with `whsec_`.

Neither of those can authenticate Settra.

## 3. Fill in Settra

Create a Stripe connection and enter:

| Settra field    | What to enter                                                     |
| --------------- | ----------------------------------------------------------------- |
| Connection name | Any useful label, such as `Stripe sandbox` or `Stripe production` |
| API Key         | The complete `sk_test_...` or `sk_live_...` secret key            |

Click **Save connection**.

## Optional: use a restricted key

For live data, a [restricted Stripe API key](https://docs.stripe.com/keys#create-restricted-api-secret-key) is safer than an unrestricted secret key. Settra only queries Stripe, so grant **Read** access to the resources you want available, including Account, Charges, Coupons, Customers, Invoices, Plans or Prices, Products, and Subscriptions.

Restricted keys begin with `rk_`. If a Settra table fails while others work, edit the key in Stripe and add read access for that resource.

## Troubleshooting

**Invalid API key**

- Confirm the key begins with `sk_` or `rk_`.
- Copy it again without spaces, quotes, or line breaks.
- Confirm the key has not been expired, deleted, or rotated in Stripe.

**The connection works but no expected data appears**

- Check whether the key belongs to a sandbox or live mode.
- Stripe objects created in a sandbox do not appear when using a live key, and live objects do not appear when using a sandbox key.

**Some tables return permission errors**

- If you used a restricted key, add **Read** permission for the affected Stripe resource.
- Retry the connection after changing key permissions.

## Security

Treat every `sk_` or `rk_` value like a password. Never commit it to Git, paste it into public documentation, or expose it in browser code. Prefer a restricted key for live data and rotate the key immediately if it is exposed.

For more details, see the [Stripe API key documentation](https://docs.stripe.com/keys) and [Steampipe Stripe plugin documentation](https://hub.steampipe.io/plugins/turbot/stripe).
