# Banners

Banners are short notices shown to every user above a new chat. Admins manage them under **Admin Settings → Interface → Banners**, or set them at deployment with `WEBUI_BANNERS` (see [[Deployment]]).

Each banner has:

- **Color**: the color of the tag before the message: blue, green, yellow, orange, red, purple, or gray. Defaults to blue.
- **Title**: short text shown inside the colored tag, such as `Release` or `Feature`. Leave it empty to show a colored dot instead.
- **Content**: the message, written in Markdown.
- **Expires after**: an optional date. The banner stops showing once that day ends in the admin's time zone, and stays in the admin list until it is removed. Without a date it shows until it is removed.
- **Dismissible**: when on, users can close the banner, and it stays closed for them in that browser.

Banners made before titles and colors existed show their old type, such as `info` or `warning`, as their title, in that type's color.
