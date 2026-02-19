# Vendor Icons

The app displays vendor/brand icons on hardware cards and detail panels.

## How icons are stored

SVG files live in `frontend/public/icons/vendors/`. They are served as static assets by Vite (dev) and Nginx (production Docker). No build step is needed when adding new icons.

A generic fallback icon (`generic.svg`) is bundled in the repo and shown automatically for any vendor without a matching SVG.

## Adding icons for a vendor

1. Download the vendor's SVG logo from a site that permits non-commercial/personal use, such as:
   - [worldvectorlogo.com](https://worldvectorlogo.com)
   - [dashboardicons.com](https://dashboardicons.com)

   You must comply with each site's terms of service. Do **not** commit brand SVGs to a public repository without verifying the applicable license.

2. Name the file to match the vendor slug used in the app (see table below), e.g. `intel.svg`.

3. Place it in `frontend/public/icons/vendors/`.

4. Restart the frontend container (or the Vite dev server) — no code change required.

## Vendor slug → file mapping

| Slug        | Expected filename         | Bundled? |
|-------------|---------------------------|----------|
| amd         | amd.svg                   | yes      |
| intel       | intel.svg                 | no (generic fallback) |
| nvidia      | nvidia.svg                | yes      |
| arm         | arm.svg                   | yes      |
| apple       | apple.svg                 | yes      |
| dell        | dell.svg                  | yes      |
| hp          | hp.svg                    | yes      |
| lenovo      | lenovo.svg                | yes      |
| supermicro  | supermicro.svg            | yes      |
| asus        | asus.svg                  | yes      |
| gigabyte    | gigabyte.svg              | no (generic fallback) |
| asrock      | asrock.svg                | yes      |
| cisco       | cisco.svg                 | yes      |
| ubiquiti    | ubiquiti.svg              | yes      |
| mikrotik    | mikrotik.svg              | yes      |
| synology    | synology.svg              | yes      |
| qnap        | qnap.svg                  | yes      |
| proxmox     | proxmox.svg               | yes      |
| other       | *(uses generic.svg)*      | yes      |

## Adding a new vendor entirely

To add a vendor that does not yet appear in the dropdown:

1. Add an entry to `frontend/src/config/vendors.js`:
   ```js
   { value: 'myvend', label: 'My Vendor' },
   ```

2. Add a mapping to `frontend/src/icons/vendorIcons.js`:
   ```js
   myvend: { label: 'My Vendor', path: '/icons/vendors/myvend.svg' },
   ```

3. Add `"myvend"` to the `VendorSlug` Literal in `backend/app/schemas/hardware.py`.

4. Drop the SVG into `frontend/public/icons/vendors/myvend.svg`.
