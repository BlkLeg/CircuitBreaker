# Auto-discovery bugs

- Live progress is still missing from the scan page.
- There should be a progress bar and the found/new metrics should update as devices are found.
- There should be a toast notification in browser that pops up once the scan is done, so the user is notified when they leave the page.
- MAC address isn't being discovered even with ARP.
- Missing real timestamp for "started" column of Scan History tab.
- Clicking a previous scan in Scan History tab should produce useful information.
- Scan job is linked with "admin" actor instead of the admin user themselves. Also missing IP. (see other working code for parity)
- For the ad-hoc scan, lets center that to the middle instead of left aligned.
- Sanity check - lets make sure the scan profiles actually have production code to back them.
