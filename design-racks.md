# Design Document: Interactive 2D Rack Elevations

## Objective
Create a highly interactive, 2D visual representation of server racks. Users should be able to define custom rack dimensions, mount hardware in various orientations, and connect devices using physics-simulated SVG cables. This feature bridges the gap between logical topology and physical reality.

## 1. Rack Configuration & Sizing
**Concept:** Not all racks are standard 42U. Users need flexibility in defining their physical space.

*   **Implementation:**
    *   **Rack Model:** Add fields for `height_u` (integer, default 42), `width_inches` (standard 19", 23", etc.), and `depth_inches` (for future-proofing, though this is 2D front/back).
    *   **UI:** A configuration panel to set the rack's name, location, and dimensions.
    *   **Visual Grid:** The 2D canvas will render a precise U-spaced grid (e.g., each U is 1.75 scale units), complete with numbered U-markers on the mounting rails.

## 2. Hardware Mounting & Drag-and-Drop
**Concept:** Intuitive placement of existing hardware assets into the physical rack space.

*   **Implementation:**
    *   **Component Library:** A sidebar listing unmounted hardware (from the `Hardware` inventory).
    *   **Drag and Drop (DnD):** Utilize `@dnd-kit/core` or `react-beautiful-dnd` for smooth, accessible drag operations from the sidebar to the rack canvas.
    *   **Sizing & Styling:** Hardware models will need new fields for physical attributes:
        *   `size_u` (e.g., 1U, 2U, 4U).
        *   `color_hex` or `theme_preset` (to distinguish servers from switches visually).
        *   `front_image_url` (optional SVG/PNG overlay for realistic rendering).
    *   **Orientation:** Support a `mounting_orientation` property (`horizontal` or `vertical`). Vertical mounting is common for zero-U PDUs or small networking gear mounted on the side rails.
    *   **Snapping:** The DnD logic must snap components precisely to the U-boundaries on the grid.

## 3. Advanced Cabling System (SVG & Physics)
**Concept:** Moving beyond simple straight lines, the cabling should feel realistic and organized, mimicking actual cable management.

*   **Implementation:**
    *   **Anchor Points (Ports):** Hardware components will define specific anchor points (x, y relative to the component bounds) representing network ports or power inlets.
    *   **Cable Types:** Distinguish cables by type (`ethernet_cat6`, `fiber_om4`, `power_c13`, `dac`) which dictate their color, thickness, and bend radius.
    *   **SVG Rendering:** Use SVG `<path>` elements with bezier curves (`C` or `Q` commands) to draw cables between anchor points.
    *   **Physics Simulation (Gravity):**
        *   Instead of straight lines, cables should droop.
        *   Calculate the control points of the bezier curve based on the distance between anchors and a simulated "gravity" constant.
        *   If Anchor A is at (x1, y1) and Anchor B is at (x2, y2), the control points pull downwards (y + offset) to create a natural sag.
    *   **Animations:** Use CSS animations or Framer Motion to animate data flow (e.g., marching ants or glowing pulses) along the SVG paths representing active connections.
    *   **Cable Management Paths:** Allow users to define invisible "cable management arm" routing points that cables must pass through before reaching their destination.

## 4. Persistence & State Management
**Concept:** The complex visual state must be reliably saved and loaded.

*   **Implementation:**
    *   **Backend Schema:**
        *   `Rack`: `id`, `name`, `u_height`.
        *   `RackAssignment`: Maps `hardware_id` to `rack_id`, `u_position`, `orientation`.
        *   `Cable`: Maps `source_port_id` to `target_port_id`, `cable_type`, `color`, `custom_routing_points` (JSON).
    *   **Auto-Save:** Debounce changes (moves, new cables) and auto-save via the API to prevent data loss during extensive modeling sessions.

## 5. User Interface Layout
1.  **Left Sidebar (Inventory):** Unmounted servers, switches, patch panels, and PDUs. Filterable by type or location.
2.  **Center Canvas (The Rack):** The interactive 2D SVG/HTML hybrid rendering area. Features zoom and pan controls.
3.  **Right Sidebar (Inspector):** Context-sensitive details. Clicking a server shows its IP, OS, and physical specs. Clicking a cable shows its type, length estimate, and connected endpoints.
4.  **Toolbar:** Controls for "Front View" vs "Rear View", toggling cable visibility (e.g., "Hide Power Cables"), and exporting the elevation as a PNG/PDF.

## Implementation Phasing
*   **Phase 1 (Foundation):** Basic rack grid, hardware size properties, and simple drag-and-drop snapping (horizontal only). Save/load coordinate state.
*   **Phase 2 (Visuals):** Color schemes, component styling, and vertical mounting support.
*   **Phase 3 (Cabling Logic):** Anchor points on components and basic point-to-point straight SVG lines.
*   **Phase 4 (Physics & Polish):** Bezier curve gravity calculations, cable types, animations, and complex routing points.