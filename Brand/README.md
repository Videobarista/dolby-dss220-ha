# Brand

This folder is for logos and artwork supplied by users of this integration.

The integration ships a plain, self-drawn cinema server icon in
`custom_components/dolby_dss220/brand/`. That icon is deliberately generic: the
Dolby marks belong to Dolby Laboratories and are not redistributed here.

If you have the right to use a manufacturer's artwork and want it on your own
installation, put your files in `custom_components/dolby_dss220/brand/`,
replacing the ones there:

| File | Size | Required |
| --- | --- | --- |
| `icon.png` | 256 x 256 | yes |
| `icon@2x.png` | 512 x 512 | yes |
| `logo.png` | any aspect ratio | no |
| `logo@2x.png` | twice the `logo.png` dimensions | no |

PNG only. Home Assistant serves these from disk, so a link to an image
elsewhere on the web will not work. The icon must be square and is used as the
logo too when no logo files are present. Transparency is preferred, and the
image should be trimmed so there is no empty space around the subject. Variants
for a dark background may be prefixed with `dark_`.

Whether you may use a manufacturer's mark is between you and that manufacturer.
