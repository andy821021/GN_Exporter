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

The following describes the JSON structure for the build format, which is used by the importer.

### Top-level fields

The importer currently supports these top-level fields:

- `format`
  - must be exactly: `geometry_nodes_ai_build`

- `format_version`
  - optional
  - recommended value: `1`

- `clear_existing_nodes`
  - optional
  - boolean
  - if `true`, existing nodes in the target tree are cleared before import
  - if omitted, Blender uses the UI option `導入前清空節點`

- `nodes`
  - required
  - array of node definitions

- `links`
  - optional
  - array of links between nodes

### Node Definition

Each entry in `nodes` represents one node to create.

#### Supported node fields

- `id`
  - recommended
  - unique identifier used by `links`
  - should be unique within the JSON

- `bl_idname`
  - required
  - Blender node type identifier
  - examples:
    - `NodeGroupInput`
    - `NodeGroupOutput`
    - `GeometryNodeSubdivideMesh`
    - `ShaderNodeMath`

- `name`
  - optional
  - Blender node name

- `label`
  - optional
  - node label shown in UI

- `location`
  - optional
  - array: `[x, y]`

- `width`
  - optional
  - numeric node width

- `mute`
  - optional
  - boolean

- `hide`
  - optional
  - boolean

- `properties`
  - optional
  - object of Blender node properties
  - used for settings such as:
    - `operation`
    - `data_type`
    - `mode`
    - `input_type`
  - unsupported properties are ignored

- `inputs`
  - optional
  - object where each key is an input socket name and each value is the default value to set

### Link Definition

Each entry in `links` describes one connection.

#### Supported link fields

- `from_node`
  - required
  - the source node `id`

- `from_socket`
  - required
  - output socket name on the source node

- `to_node`
  - required
  - target node `id`

- `to_socket`
  - required
  - input socket name on the target node

If a node ID or socket name cannot be found, that link is skipped.

---

## Minimal Valid Example

```json
{
  "format": "geometry_nodes_ai_build",
  "format_version": 1,
  "clear_existing_nodes": true,
  "nodes": [
    {
      "id": "input",
      "bl_idname": "NodeGroupInput",
      "location": [-400, 0]
    },
    {
      "id": "subdivide",
      "bl_idname": "GeometryNodeSubdivideMesh",
      "location": [-100, 0],
      "inputs": {
        "Level": 3
      }
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

## Example with Node Properties

This example shows how AI can set node properties in addition to default input values.

```json
{
  "format": "geometry_nodes_ai_build",
  "format_version": 1,
  "clear_existing_nodes": true,
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
      "inputs": {
        "Value": 2.0,
        "Value_001": 3.0
      }
    }
  ],
  "links": []
}
```

> Note: whether an input socket name is `Value`, `Value_001`, or something else depends on the Blender node type.
> AI should use the actual socket names Blender expects.

---

## Rules for AI When Generating Import JSON

When asking AI to generate importable JSON, use these rules:

1. Always set:
   - `format: "geometry_nodes_ai_build"`

2. Always provide:
   - `nodes`

3. Prefer giving every node a unique:
   - `id`

4. For every node, provide the correct Blender:
   - `bl_idname`

5. Use socket **names**, not indices, in:
   - `inputs`
   - `links.from_socket`
   - `links.to_socket`

6. Only use `properties` for real Blender node properties.

7. Keep the first test simple:
   - `NodeGroupInput`
   - one geometry processing node
   - `NodeGroupOutput`

8. If unsure about a node property, omit it.

9. If unsure about a socket default value, omit it.

10. Use simple graphs first before attempting complex multi-branch setups.

---

## Recommended Prompt for AI

You can ask AI like this:

```text
請幫我輸出一份 Blender Geometry Nodes 可匯入的 JSON，格式必須是 geometry_nodes_ai_build。

要求：
1. 只能輸出合法 JSON
2. format 必須是 geometry_nodes_ai_build
3. 每個 node 都要有 id 與 bl_idname
4. links 要使用 node id 與 socket 名稱
5. 若不確定 Blender 屬性名稱，就不要輸出 properties
6. 請先生成最小可運作版本
```

---

## Recommended First Test Cases

For project testing, start with these simple structures:

### Test 1: Group Input → Subdivide Mesh → Group Output
Goal:
- verify node creation
- verify socket default value assignment
- verify link creation

### Test 2: Group Input → Set Position → Group Output
Goal:
- verify another Geometry Nodes type
- verify different socket names

### Test 3: Math node only
Goal:
- verify generic property assignment such as `operation`

---

## Current Importer Limitations

The current importer is intentionally minimal.

### Supported now

- create nodes by `bl_idname`
- set basic node fields
- set some node properties through `properties`
- set some input default values through `inputs`
- create links by socket names
- optionally clear existing nodes before import

### Not fully supported yet

- automatic import of nested group JSON files
- automatic creation of custom group interfaces
- complete reconstruction from exported analysis JSON
- advanced Blender-only internal node state
- all possible node-specific special settings
- full validation of socket/property compatibility

Because of this, the best testing approach is:

- start with small graphs
- validate socket names carefully
- gradually expand complexity

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
