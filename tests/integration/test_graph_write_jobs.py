from tests.integration.test_graph_write_worker import (
    test_graph_write_worker_ingests_job_writes_links_and_audit as _assert_graph_write_success,
)
from tests.integration.test_graph_write_worker_failures import (
    test_graph_write_worker_retries_backend_timeout_without_hanging as _assert_graph_write_timeout_retry,
)
from tests.integration.test_graph_write_worker_invalidation import (
    test_graph_write_worker_marks_invalidated_fact_memories_needs_review as _assert_graph_write_invalidation,
)
from tests.integration.test_graph_write_worker_locking import (
    test_graph_write_worker_lost_lock_does_not_write_links_or_lifecycle_side_effects as _assert_graph_write_lock_lost,
)


def test_graph_write_jobs_success_retry_locking_and_invalidation_contracts() -> None:
    _assert_graph_write_success()
    _assert_graph_write_timeout_retry()
    _assert_graph_write_lock_lost()
    _assert_graph_write_invalidation()
