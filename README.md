# GN AI JSON Exporter

## Overview

`GN AI JSON Exporter` exports Blender `Geometry Nodes` trees into AI-readable JSON files.

The exporter supports:

- one **main tree JSON**
- multiple **group tree JSON** files exported separately

This separation helps AI read large node graphs incrementally instead of loading every nested group into a single oversized JSON file.

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

## Summary

This exporter is designed for **hierarchical AI parsing** of Geometry Nodes:

- main graph in one file
- nested group graphs in separate files
- explicit references between them
- stable structure for analysis, documentation, and reconstruction
