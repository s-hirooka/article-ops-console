# Bundled fonts

## NotoSansJP-VF.ttf

**Noto Sans JP** (variable font, Weight axis 100–900), SIL Open Font License 1.1
— see [`OFL.txt`](OFL.txt). Redistribution bundled with software is explicitly
permitted by the license.

This replaces the Windows-only, non-redistributable **Yu Gothic** (`YuGoth*.ttc`)
that the local eyecatch scripts used. `app/integrations/eyecatch.py` aliases the
old file names to Noto weights, so existing generators keep working:

| Legacy name    | Noto weight |
|----------------|-------------|
| `YuGothL.ttc`  | 300         |
| `YuGothR.ttc`  | 400         |
| `YuGothM.ttc`  | 500         |
| `YuGothB.ttc`  | 700         |

Override the directory with the `EYECATCH_FONT_DIR` env var if needed.
