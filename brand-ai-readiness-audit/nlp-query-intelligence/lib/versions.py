"""Version stamps embedded in every artifact this subsystem writes.

Bump the relevant constant whenever the corresponding logic changes in a way
that could change output for the same input — that is what makes a
generated-queries.json or query-result.json reproducible and comparable
across runs.
"""

PIPELINE_VERSION = "0.1.0"
TAXONOMY_VERSION = "0.1.0"      # lib/vocabulary.py
PROFILER_VERSION = "0.1.0"      # lib/domain_profiler.py
GENERATOR_VERSION = "0.1.0"     # lib/query_generator.py + query_templates.py
NLP_ENGINE_VERSION = "0.1.0"    # lib/nlp_engine.py
SCORING_VERSION = "0.1.0"       # lib/scoring.py
DATASET_VERSION = "0.1.0"
