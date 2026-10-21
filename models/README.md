# Models

Model weights are never committed. The engine reads its model manifests from
`services/local-engine/omnirecall/model_manifests/` (packaged with the engine so
the frozen sidecar carries them; decision D-015). Each manifest pins the
upstream revision, license, download URL, size, and checksums.

Models are installed into `<AppData>/models/<model-id>/` only by explicit user
action (Settings → Models) or from a local archive the user selects.
