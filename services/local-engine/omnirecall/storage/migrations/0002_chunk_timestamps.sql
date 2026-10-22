-- Transcript chunks keep where they start and end in the recording (Phase 5).
-- NULL for chunks from text, documents, and images.
ALTER TABLE chunks ADD COLUMN start_ms INTEGER;
ALTER TABLE chunks ADD COLUMN end_ms INTEGER;
