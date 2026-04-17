# GN AI JSON Exporter

## Overview

`GN AI JSON Exporter` exports Blender `Geometry Nodes` trees into AI-readable JSON files.

The addon currently supports two directions:

- **Export** Blender Geometry Nodes into AI-readable JSON
- **Import** AI-generated build JSON into an existing Geometry Nodes tree

This makes it possible to:

1. export an existing node tree for AI analysis
2. ask AI to generate a new node graph in a supported JSON format
3. import that JSON back into Blender with one click

---

## Supported JSON Formats

The addon currently works with **two different JSON purposes**:

### 1. `geometry_nodes_ai_json`
Used for **analysis / documentation / AI understanding**.

This is the exporter format.
It is designed so AI can read and understand an existing Geometry Nodes graph.

### 2. `geometry_nodes_ai_build`
Used for **building / importing / generating nodes in Blender**.

This is the importer format.
It is the format AI should generate if you want Blender to create a node graph from JSON.

> Important: the importer does **not** read the exported analysis JSON directly.
> It reads the dedicated build format: `geometry_nodes_ai_build`.

---

## Purpose

This format is designed to help AI systems and tooling:

- understand Geometry Nodes graph structure
- inspect nodes, sockets, and links
- trace data flow between nodes
- discover referenced Group Nodes
- load nested group trees from separate JSON files
- generate explanations, documentation, or reconstruction steps

---

## Export Output

A typical export may generate:

- `MyObject_MyModifier_GeometryNodes.json`
- `MyObject_MyModifier_GeometryNodes__group_01_SurfaceScatter.json`
- `MyObject_MyModifier_GeometryNodes__group_02_RandomScale.json`

### Export behavior

- The main JSON contains the primary exported node tree.
- Each referenced Geometry Nodes group can be exported as a separate JSON file.
- The main JSON contains references to those group JSON files.
- Group JSON files may also reference deeper nested group JSON files.

---

## Top-Level JSON Schema

Both main and group JSON files use the same base structure.

### Common top-level fields

- `format`  
  Fixed string: `geometry_nodes_ai_json`

- `format_version`  
  Current format version.  
  `2` indicates support for separate group exports.

- `generator`  
  Exporter name.

- `blender_version`  
  Blender version as an array, for example:  
  `[4, 5, 0]`

- `source`  
  Export source. Possible values:
  - `geometry_node_editor`
  - `modifier_panel`
  - `group_node_tree`

- `export_role`  
  Indicates file role:
  - `main_tree`
  - `group_tree`

- `object_name`  
  Active object name, or `null`

- `modifier_name`  
  Geometry Nodes modifier name, or `null`

- `tree`  
  Main node tree payload

### Main JSON only

The main export may contain:

- `group_exports`
- `group_export_count`

### Group JSON only

A group export may contain:

- `root_tree_name`
- `group_file`

---

## Main JSON ? Group JSON Relationship

When a node is a Group Node, its serialized node data may contain:

- `referenced_node_tree.name`
- `referenced_node_tree.bl_idname`
- `referenced_node_tree.export_file`

Example:

```json
"referenced_node_tree": {
  "name": "SurfaceScatter",
  "bl_idname": "GeometryNodeTree",
  "export_file": "Geometry_Nodes__group_01_SurfaceScatter.json"
}
```

This means:

- the node references another Geometry Nodes tree
- that referenced tree was exported separately
- the AI should load `export_file` if deeper analysis is needed

The main JSON may also include a summary list:

```json
"group_exports": [
  {
    "tree_name": "SurfaceScatter",
    "file": "Geometry_Nodes__group_01_SurfaceScatter.json"
  }
]
```

---

## `tree` Object

The `tree` object contains the exported node graph.

### Fields

- `name`  
  Node tree name

- `bl_idname`  
  Usually `GeometryNodeTree`

- `selection_mode`  
  Export scope:
  - `all_nodes`
  - `selected_nodes`
  - `all_nodes_fallback_no_selection`

- `node_count`  
  Number of exported nodes

- `link_count`  
  Number of exported links

- `nodes`  
  Array of serialized nodes

- `links`  
  Array of serialized links

---

## Node Structure

Each item in `tree.nodes` represents one node.

### Common node fields

- `name`
- `label`
- `type`
- `bl_idname`
- `location`
- `width`
- `height`
- `selected`
- `muted`
- `hidden`
- `inputs`
- `outputs`

### Group node reference

If the node references another node tree, it may also contain:

- `referenced_node_tree.name`
- `referenced_node_tree.bl_idname`
- `referenced_node_tree.export_file`

AI should treat this as an external subtree reference.

---

## Socket Structure

Each socket in `inputs` or `outputs` may contain:

- `name`
- `identifier`
- `type`
- `bl_idname`
- `is_linked`
- `is_multi_input`
- `default_value` *(optional)*

### Notes

- `default_value` may be a scalar, string, boolean, array, matrix-like array, or stringified fallback value.
- Missing `default_value` does not imply the socket has no value; it may simply be unsupported or context-dependent.

---

## Link Structure

Each item in `tree.links` describes one connection:

- `from_node`
- `from_socket`
- `to_node`
- `to_socket`

These links define graph flow between serialized nodes.

---

## AI Parsing Strategy

Recommended parse order:

1. Load the **main JSON**
2. Read top-level metadata
3. Parse `tree.nodes`
4. Parse `tree.links`
5. Build a node index using `node.name`
6. Detect nodes with `referenced_node_tree.export_file`
7. Load the referenced group JSON files only when needed
8. Recursively repeat for nested groups

---

## Interpretation Rules for AI

### 1. Treat the main file as the graph entry point

If `export_role == "main_tree"`, this file is the primary graph.

### 2. Treat group files as external subgraphs

If `export_role == "group_tree"`, this file is a referenced subtree, not the primary root.

### 3. Use `export_file` as the authoritative link to child graphs

If present, `referenced_node_tree.export_file` is the file the AI should load for subtree inspection.

### 4. Do not assume `label` is unique

`label` is user-facing only and may be empty.

### 5. Prefer `name` for link matching

Links use node names and socket names.  
Node `name` is the practical key for reconstruction.

### 6. Respect `selection_mode`

If the main export used `selected_nodes`, the JSON may represent only a partial graph.

### 7. Group exports are full subtree exports

Group JSON files are exported as complete trees and are intended to supplement the main graph.

---

## Main JSON Example

```json
{
  "format": "geometry_nodes_ai_json",
  "format_version": 2,
  "generator": "GN AI JSON Exporter",
  "blender_version": [4, 5, 0],
  "source": "geometry_node_editor",
  "export_role": "main_tree",
  "object_name": null,
  "modifier_name": null,
  "group_exports": [
    {
      "tree_name": "SurfaceScatter",
      "file": "Geometry_Nodes__group_01_SurfaceScatter.json"
    }
  ],
  "group_export_count": 1,
  "tree": {
    "name": "Geometry Nodes",
    "bl_idname": "GeometryNodeTree",
    "selection_mode": "all_nodes",
    "node_count": 1,
    "link_count": 0,
    "nodes": [
      {
        "name": "Surface Scatter",
        "label": "",
        "type": "GROUP",
        "bl_idname": "GeometryNodeGroup",
        "location": [0.0, 0.0],
        "width": 180.0,
        "height": 100.0,
        "selected": false,
        "muted": false,
        "hidden": false,
        "inputs": [],
        "outputs": [],
        "referenced_node_tree": {
          "name": "SurfaceScatter",
          "bl_idname": "GeometryNodeTree",
          "export_file": "Geometry_Nodes__group_01_SurfaceScatter.json"
        }
      }
    ],
    "links": []
  }
}
```

---

## Group JSON Example

```json
{
  "format": "geometry_nodes_ai_json",
  "format_version": 2,
  "generator": "GN AI JSON Exporter",
  "blender_version": [4, 5, 0],
  "source": "group_node_tree",
  "export_role": "group_tree",
  "object_name": null,
  "modifier_name": null,
  "root_tree_name": "Geometry Nodes",
  "group_file": "Geometry_Nodes__group_01_SurfaceScatter.json",
  "tree": {
    "name": "SurfaceScatter",
    "bl_idname": "GeometryNodeTree",
    "selection_mode": "all_nodes",
    "node_count": 2,
    "link_count": 1,
    "nodes": [
      {
        "name": "Group Input",
        "label": "",
        "type": "GROUP_INPUT",
        "bl_idname": "NodeGroupInput",
        "location": [-300.0, 0.0],
        "width": 140.0,
        "height": 100.0,
        "selected": false,
        "muted": false,
        "hidden": false,
        "inputs": [],
        "outputs": []
      },
      {
        "name": "Group Output",
        "label": "",
        "type": "GROUP_OUTPUT",
        "bl_idname": "NodeGroupOutput",
        "location": [200.0, 0.0],
        "width": 140.0,
        "height": 100.0,
        "selected": false,
        "muted": false,
        "hidden": false,
        "inputs": [],
        "outputs": []
      }
    ],
    "links": [
      {
        "from_node": "Group Input",
        "from_socket": "Geometry",
        "to_node": "Group Output",
        "to_socket": "Geometry"
      }
    ]
  }
}
```

---

## Suggested AI Tasks

This export format is suitable for prompts such as:

- Explain what this Geometry Nodes graph does
- Describe the node graph as step-by-step logic
- Reconstruct the graph hierarchy including nested groups
- Identify unused nodes or disconnected branches
- Summarize data flow from input to output
- Generate technical documentation for the node tree
- Produce a human-readable breakdown of each group subtree

---

## Recommended Workflow for AI Agents

1. Load the main export
2. Parse nodes and links
3. Collect all `referenced_node_tree.export_file` values
4. Load each referenced group JSON
5. Build parent-child tree relationships
6. Merge structural understanding logically, but keep file boundaries intact
7. Generate analysis or reconstruction output

---

## `geometry_nodes_ai_build` Format

The following describes the current importer format used by Blender to create Geometry Nodes from AI-generated JSON.

The current addon supports:

- richer node properties
- recursive group import
- group interface reconstruction from JSON
- `group_file` and `group_data`
- socket targeting by `name`, `identifier`, or `index`
- import control flags such as `append_mode`, `place_offset`, and `strict_mode`

---

## Build Format Version

- `format` must be exactly: `geometry_nodes_ai_build`
- current supported `format_version`: up to `3`
- recommended value for new AI output: `3`

---

## Top-Level Fields

### Required

- `format`
- `nodes`

### Recommended

- `format_version`
- `links`
- `metadata`

### Supported top-level fields

- `format`
  - must be `geometry_nodes_ai_build`

- `format_version`
  - optional
  - recommended: `2`

- `nodes`
  - required
  - array of node definitions

- `links`
  - optional
  - array of links between nodes

- `interface`
  - optional
  - describes tree input/output interface sockets
  - recommended for any JSON that contains `NodeGroupInput`, `NodeGroupOutput`, or `GeometryNodeGroup`

- `clear_existing_nodes`
  - optional
  - boolean
  - if `true`, clear target tree before import
  - if omitted, Blender uses the UI option

- `append_mode`
  - optional
  - boolean
  - if `true`, importer will not clear existing nodes even if `clear_existing_nodes` is true

- `place_offset`
  - optional
  - array: `[x, y]`
  - offsets all imported node locations

- `strict_mode`
  - optional
  - boolean
  - if `true`, importer throws error on invalid group/socket/link
  - if `false`, importer records warnings and continues when possible

- `metadata`
  - optional
  - object for descriptive/import validation information

- `generator`
  - optional
  - text description of the system that generated the JSON

- `description`
  - optional
  - human-readable summary of what the graph is supposed to do

- `group_interface`
  - optional compatibility alias for `interface`

---

## `metadata` Object

Supported metadata fields:

- `generator`
- `description`
- `target_blender_version`

Example:

```json
"metadata": {
  "generator": "AI test generator",
  "description": "Create a simple subdivide setup",
  "target_blender_version": [4, 5, 0]
}
```

Notes:

- if `target_blender_version` is higher than the current Blender version, import will fail
- top-level `generator` and `description` are also accepted for compatibility

---

## Tree `interface` Definition

The importer now supports explicit tree interface reconstruction.

This is important for:

- `NodeGroupInput`
- `NodeGroupOutput`
- `GeometryNodeGroup`
- nested group trees imported through `group_file` or `group_data`

Without a matching interface, a group node may exist but still not expose the correct sockets for links.

### Recommended shape

```json
"interface": {
  "inputs": [
    {
      "name": "Geometry",
      "socket_type": "NodeSocketGeometry"
    },
    {
      "name": "Density",
      "socket_type": "NodeSocketFloat",
      "default_value": 1.0,
      "min_value": 0.0,
      "max_value": 100.0
    }
  ],
  "outputs": [
    {
      "name": "Geometry",
      "socket_type": "NodeSocketGeometry"
    }
  ]
}
```

### Supported item fields

Each interface item may use:

- `name`
- `in_out` *(only needed for flat list form)*
- `socket_type`
- `bl_socket_idname`
- `socket_idname`
- `type` *(mapped to a Blender socket type when possible)*
- `description`
- `default_value`
- `min_value`
- `max_value`
- `hide_value`
- `attribute_domain`
- `default_attribute_name`

### Supported forms

#### Object form with `inputs` / `outputs`

```json
"interface": {
  "inputs": [
    { "name": "Geometry", "socket_type": "NodeSocketGeometry" }
  ],
  "outputs": [
    { "name": "Geometry", "socket_type": "NodeSocketGeometry" }
  ]
}
```

#### Flat list form

```json
"interface": [
  { "in_out": "INPUT", "name": "Geometry", "socket_type": "NodeSocketGeometry" },
  { "in_out": "OUTPUT", "name": "Geometry", "socket_type": "NodeSocketGeometry" }
]
```

Notes:

- interface sockets are created before nodes and links are imported
- this allows `NodeGroupInput` / `NodeGroupOutput` sockets to exist during link reconstruction
- for stable results, AI should always provide `interface` when building custom groups

---

## Node Definition

Each entry in `nodes` represents one node to create.

### Common node fields

- `id`
  - recommended unique ID used by `links`

- `bl_idname`
  - required Blender node type identifier

- `name`
  - optional Blender node name

- `label`
  - optional UI label

- `location`
  - optional `[x, y]`

- `width`
  - optional numeric width

- `mute`
  - optional boolean

- `hide`
  - optional boolean

- `properties`
  - optional object of Blender properties set via `setattr`
  - importer includes a property restorer with ordered application for common high-frequency nodes

- `custom_properties`
  - optional object of Blender custom properties / ID properties

- `warnings_optional`
  - optional array of warning strings
  - importer will record them as warnings for visibility

- `inputs`
  - optional
  - supports both simple and extended forms

---

## Special Node Property Restoration

The importer now includes a node property restorer for common Blender / Geometry Nodes cases where property order matters.

This is important because some nodes must have their type-defining properties set before sockets or inputs can be applied correctly.

Examples:

- `ShaderNodeMath` needs `operation`
- `FunctionNodeCompare` often needs `data_type` before `operation`
- `GeometryNodeSwitch` needs `input_type`
- `GeometryNodeCaptureAttribute` needs `data_type` and `domain`
- `GeometryNodeStoreNamedAttribute` needs `data_type` and `domain`

### How the importer applies properties

The importer uses this strategy:

1. apply prioritized special properties first
2. apply remaining generic `properties`
3. apply `inputs` after properties

This reduces failures caused by sockets changing after type-related settings are changed.

### Supported aliases

The importer currently supports a small alias layer:

- `use_clamp` → `clamp`

This allows AI to use either spelling in JSON.

### Current high-frequency node-specific handling

The importer currently has explicit property priority rules for:

- `ShaderNodeMath`
  - `operation`
  - `clamp`

- `FunctionNodeCompare`
  - `data_type`
  - `mode`
  - `operation`

- `GeometryNodeSwitch`
  - `input_type`

- `GeometryNodeCaptureAttribute`
  - `data_type`
  - `domain`
  - dynamic `capture_items`

- `GeometryNodeStoreNamedAttribute`
  - `data_type`
  - `domain`

- `GeometryNodeAttributeDomainSize`
  - `component`

- `GeometryNodeSampleIndex`
  - `data_type`
  - `domain`
  - `clamp`

- `GeometryNodeRaycast`
  - `data_type`
  - `mapping`

### Default prioritized properties

Even when a node has no explicit handler, the importer still tries to prioritize these common properties before other generic ones:

- `data_type`
- `input_type`
- `component`
- `domain`
- `mode`
- `operation`
- `rotation_type`
- `transform_space`
- `interpolation_type`
- `clamp`

### Failure behavior

If a property cannot be applied:

- in normal mode: importer records a warning and continues
- in `strict_mode`: importer raises an error

This makes the importer safer for AI-generated JSON while still reporting unsupported properties.

### Example

```json
{
  "format": "geometry_nodes_ai_build",
  "format_version": 3,
  "nodes": [
    {
      "id": "compare_1",
      "bl_idname": "FunctionNodeCompare",
      "location": [0, 0],
      "properties": {
        "data_type": "FLOAT",
        "mode": "ELEMENT",
        "operation": "GREATER_THAN"
      },
      "inputs": {
        "A": 1.0,
        "B": 0.5
      }
    },
    {
      "id": "switch_1",
      "bl_idname": "GeometryNodeSwitch",
      "location": [250, 0],
      "properties": {
        "input_type": "GEOMETRY"
      }
    }
  ],
  "links": []
}
```

For AI generation, prefer supplying these type-defining properties explicitly for the node types above.

### Dynamic items for special nodes

Some Blender nodes need extra internal items to be created before the final sockets exist.

The importer now supports this for:

- `GeometryNodeCaptureAttribute`

It also now retries socket resolution during input assignment and link creation,
including a dynamic-item fallback for `GeometryNodeCaptureAttribute` when the
requested socket does not exist yet.

Supported JSON fields:

- `capture_items`
- `dynamic_items.capture_items`

Example:

```json
{
  "id": "capture_attr",
  "bl_idname": "GeometryNodeCaptureAttribute",
  "properties": {
    "data_type": "FLOAT",
    "domain": "POINT"
  },
  "capture_items": [
    {
      "name": "MyCapturedValue",
      "data_type": "FLOAT"
    }
  ]
}
```

Why this matters:

- Blender creates some sockets only after the internal item exists
- without that item, links may fail even if the node itself was created correctly
- this is the beginning of support for more advanced dynamic-item nodes in future versions

---

## `inputs` Supported Forms

### Simple form

```json
"inputs": {
  "Level": 3,
  "Selection": true
}
```

### Extended object form

```json
"inputs": {
  "Level": {
    "identifier": "Level",
    "value": 3
  }
}
```

### Array form

```json
"inputs": [
  {
    "name": "Level",
    "value": 3
  },
  {
    "identifier": "Selection",
    "value": true
  },
  {
    "index": 0,
    "value": 1.0
  }
]
```

Each input reference can use:

- `name`
- `identifier`
- `index`

Value fields supported:

- `value`
- `default_value`

Recommended priority for AI:

1. use `identifier` if known
2. otherwise use `name`
3. use `index` only if name/identifier are unstable or unavailable

---

## Group Node Support

If a node is a group node such as `GeometryNodeGroup`, it may reference a child group tree.

Supported group fields on a node:

- `group_name`
- `group_file`
- `group_data`

### `group_name`

Use an existing Blender `GeometryNodeTree` by name if available.

### `group_file`

Load a child JSON file relative to the current JSON file.

Example:

```json
{
  "id": "surface_group",
  "bl_idname": "GeometryNodeGroup",
  "group_name": "SurfaceScatter",
  "group_file": "groups/surface_scatter.json"
}
```

### `group_data`

Embed a child build JSON directly inside the node.

Example:

```json
{
  "id": "inner_group",
  "bl_idname": "GeometryNodeGroup",
  "group_name": "InlineScatter",
  "group_data": {
    "format": "geometry_nodes_ai_build",
    "format_version": 2,
    "nodes": [
      {
        "id": "input",
        "bl_idname": "NodeGroupInput",
        "location": [-250, 0]
      },
      {
        "id": "output",
        "bl_idname": "NodeGroupOutput",
        "location": [250, 0]
      }
    ],
    "links": []
  }
}
```

Notes:

- `group_data` may also use simplified form without explicitly repeating `format`
- importer supports recursive nested groups
- importer caches repeated group references during one import session
- importer blocks circular group references

---

## Link Definition

Each entry in `links` describes one connection.

### Required link fields

- `from_node`
- `to_node`

### Socket reference fields

Each side may use either a direct socket reference object or compatibility fields.

#### Direct form

```json
{
  "from_node": "input",
  "from_socket": {
    "identifier": "Geometry"
  },
  "to_node": "subdivide",
  "to_socket": {
    "name": "Mesh"
  }
}
```

#### Compatibility form

```json
{
  "from_node": "input",
  "from_socket_name": "Geometry",
  "to_node": "subdivide",
  "to_socket_name": "Mesh"
}
```

#### Old simple form

```json
{
  "from_node": "input",
  "from_socket": "Geometry",
  "to_node": "subdivide",
  "to_socket": "Mesh"
}
```

Supported socket targeting keys:

- `name`
- `identifier`
- `index`

If a node or socket cannot be found:

- in normal mode: importer records a warning and skips that link
- in `strict_mode`: importer raises an error

---

## Minimal Valid Example

```json
{
  "format": "geometry_nodes_ai_build",
  "format_version": 3,
  "clear_existing_nodes": true,
  "metadata": {
    "generator": "AI test generator",
    "description": "Simple subdivide mesh graph",
    "target_blender_version": [4, 5, 0]
  },
  "nodes": [
    {
      "id": "input",
      "bl_idname": "NodeGroupInput",
      "location": [-400, 0]
    },
    {
      "id": "subdivide",
      "bl_idname": "GeometryNodeSubdivideMesh",
      "location": [-80, 0],
      "inputs": {
        "Level": 3
      }
    },
    {
      "id": "output",
      "bl_idname": "NodeGroupOutput",
      "location": [240, 0]
    }
  ],
  "links": [
    {
      "from_node": "input",
      "from_socket": "Geometry",
      "to_node": "subdivide",
      "to_socket": "Mesh"
    },
    {
      "from_node": "subdivide",
      "from_socket": "Mesh",
      "to_node": "output",
      "to_socket": "Geometry"
    }
  ]
}
```

---

## Example with Properties and Stable Socket References

```json
{
  "format": "geometry_nodes_ai_build",
  "format_version": 3,
  "clear_existing_nodes": true,
  "strict_mode": false,
  "nodes": [
    {
      "id": "math_1",
      "bl_idname": "ShaderNodeMath",
      "name": "Multiply Value",
      "label": "Scale Multiplier",
      "location": [0, 100],
      "properties": {
        "operation": "MULTIPLY"
      },
      "custom_properties": {
        "ai_tag": "generated"
      },
      "inputs": [
        {
          "identifier": "Value",
          "value": 2.0
        },
        {
          "index": 1,
          "value": 3.0
        }
      ]
    }
  ],
  "links": []
}
```

---

## Example with External Recursive Group

Main JSON:

```json
{
  "format": "geometry_nodes_ai_build",
  "format_version": 3,
  "clear_existing_nodes": true,
  "interface": {
    "inputs": [
      {
        "name": "Geometry",
        "socket_type": "NodeSocketGeometry"
      }
    ],
    "outputs": [
      {
        "name": "Geometry",
        "socket_type": "NodeSocketGeometry"
      }
    ]
  },
  "nodes": [
    {
      "id": "group_input",
      "bl_idname": "NodeGroupInput",
      "location": [-500, 0]
    },
    {
      "id": "scatter_group",
      "bl_idname": "GeometryNodeGroup",
      "group_name": "SurfaceScatter",
      "group_file": "surface_scatter.json",
      "location": [-100, 0]
    },
    {
      "id": "group_output",
      "bl_idname": "NodeGroupOutput",
      "location": [300, 0]
    }
  ],
  "links": [
    {
      "from_node": "group_input",
      "from_socket": "Geometry",
      "to_node": "scatter_group",
      "to_socket": "Geometry"
    },
    {
      "from_node": "scatter_group",
      "from_socket": "Geometry",
      "to_node": "group_output",
      "to_socket": "Geometry"
    }
  ]
}
```

Child `surface_scatter.json`:

```json
{
  "format": "geometry_nodes_ai_build",
  "format_version": 3,
  "interface": {
    "inputs": [
      {
        "name": "Geometry",
        "socket_type": "NodeSocketGeometry"
      }
    ],
    "outputs": [
      {
        "name": "Geometry",
        "socket_type": "NodeSocketGeometry"
      }
    ]
  },
  "nodes": [
    {
      "id": "input",
      "bl_idname": "NodeGroupInput",
      "location": [-250, 0]
    },
    {
      "id": "output",
      "bl_idname": "NodeGroupOutput",
      "location": [250, 0]
    }
  ],
  "links": [
    {
      "from_node": "input",
      "from_socket": "Geometry",
      "to_node": "output",
      "to_socket": "Geometry"
    }
  ]
}
```

---

## Rules for AI When Generating Import JSON

Use these rules for reliable generation:

1. Always set `format` to `geometry_nodes_ai_build`
2. Prefer `format_version: 3`
3. Give every node a unique `id`
4. Every node must have the correct Blender `bl_idname`
5. Prefer socket `identifier` over `name` when known
6. Use `index` only as fallback
7. Only put real Blender attributes in `properties`
8. Use `custom_properties` only for custom metadata tags
9. When a graph uses `NodeGroupInput`, `NodeGroupOutput`, or `GeometryNodeGroup`, provide `interface`
10. For group nodes, prefer `group_file` for larger modular structures
11. For small self-contained tests, use `group_data`
12. For nodes like `Compare`, `Switch`, `Math`, `Capture Attribute`, and `Store Named Attribute`, explicitly provide their type-defining `properties`
13. For `GeometryNodeCaptureAttribute`, also provide `capture_items` when the captured value socket is needed
14. If uncertain about a property or socket, omit it
15. Keep early tests structurally simple

---

## Recommended Prompt for AI

```text
請幫我輸出一份 Blender Geometry Nodes 可匯入的 JSON，格式必須是 geometry_nodes_ai_build。

要求：
1. 只能輸出合法 JSON
2. format 必須是 geometry_nodes_ai_build
3. format_version 請使用 3
4. 每個 node 都要有 id 與 bl_idname
5. links 要使用 node id
6. socket 若知道 identifier 就優先用 identifier，否則用 name
7. 若有 Group Input、Group Output、或 Group Node，請一併輸出 interface
8. 若是 Group Node，可使用 group_file 或 group_data
9. 若不確定 Blender 屬性名稱，就不要輸出 properties
10. 請先生成最小可運作版本
11. 不要輸出解說文字，只輸出 JSON
```

---

## Recommended AI Test Cases

### Test 1: Group Input → Subdivide Mesh → Group Output
Goal:
- verify node creation
- verify input default values
- verify basic link creation

### Test 2: Node with `properties` and `custom_properties`
Goal:
- verify property assignment
- verify custom property assignment

### Test 3: Socket targeting with `identifier`
Goal:
- verify more stable socket matching

### Test 4: Main graph with one `group_file`
Goal:
- verify external child group creation
- verify group node points to imported node tree
- verify group interface sockets appear correctly on the parent group node

### Test 5: Nested `group_file` inside another group
Goal:
- verify recursive group import
- verify cycle protection does not falsely trigger

### Test 6: Custom group interface with float + geometry sockets
Goal:
- verify explicit interface reconstruction
- verify `NodeGroupInput` / `NodeGroupOutput` links work after import

---

## Current Importer Limitations

Supported now:

- create nodes by `bl_idname`
- set basic node fields
- set `properties`
- set `custom_properties`
- set input values using `name`, `identifier`, or `index`
- create links using `name`, `identifier`, or `index`
- reconstruct tree interface from JSON `interface`
- restore special high-frequency node properties in safer order
- restore dynamic items for `GeometryNodeCaptureAttribute`
- retry socket lookup with fuzzy name matching during input and link reconstruction
- attempt dynamic socket creation before failing `GeometryNodeCaptureAttribute` links
- recursively import nested group JSON
- load `group_file` relative to the current JSON file
- load inline `group_data`
- detect circular group references
- reuse repeated group references during a single import session

Not fully supported yet:

- complete reconstruction from exported analysis JSON
- all Blender internal special node states
- full coverage for all high-frequency Blender and Geometry Nodes special property combinations
- full coverage for all dynamic-item node families such as future index-switch style nodes
- advanced interface features such as panels or every possible socket-specific UI behavior
- full validation of every node/property/socket combination
- advanced merge behavior for imported groups beyond current append/clear controls

---

## Export Format Summary

For completeness, the addon also exports analysis JSON using `geometry_nodes_ai_json`.

That format is intended for:

- AI understanding
- graph analysis
- documentation
- reverse engineering

It is not the same as the importer format.

---

## Summary

If you want AI to generate a node graph that Blender can import, the AI must output:

- `format: "geometry_nodes_ai_build"`

The JSON should contain:

- `nodes`
- optional `links`
- optional `properties`
- optional `inputs`

For the first round of testing, keep the structure small and explicit.
