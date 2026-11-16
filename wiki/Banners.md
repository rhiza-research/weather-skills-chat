# Banners

Banners are short notices shown to every user above a new chat. Admins manage them under **Admin Settings → Interface → Banners**, or set them at deployment with `WEBUI_BANNERS` (see [[Deployment]]).

Each banner has:

- **Label**: short text shown in a colored tag before the message, such as `Maintenance`. Leave it empty to show the message without a tag.
- **Label color**: one of blue, green, yellow, orange, red, purple, or gray. Defaults to blue.
- **Content**: the message, written in Markdown.
- **Expires after**: an optional date. The banner stops showing once that day ends in the admin's time zone, and stays in the admin list until it is removed. Without a date it shows until it is removed.
- **Dismissible**: when on, users can close the banner, and it stays closed for them in that browser.

Banners made before labels and colors existed keep their old type, such as `info` or `warning`, as their label, in that type's color.
