# studio/projects/

Each subdirectory is one saved project. Layout:

```
<project-slug>/
├── scene.json     # full scene + flow graph (single source of truth)
├── assets/        # project-local asset copies / overrides
├── exports/       # rendered exports (PNG, MP4, GLB, …)
├── makeup/        # makeup-designer JSONL layer stacks
├── renders/       # raster renders of the 3-D scene
└── layers/        # SVG layer drops from the designer wizards
```

Use `project_io.new(name)` to create, `project_io.list_projects()` to enumerate.
