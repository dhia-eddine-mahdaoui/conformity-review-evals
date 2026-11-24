import pytest

from crev import evals, pipeline


def _suite(**kw):
    runs = [(c, pipeline.run(c["data"], c["requirements"], title=c["title"], **kw)) for c in pipeline.load_suite()]
    return runs, evals.evaluate_suite(runs)


@pytest.fixture(scope="session")
def suite_runs():
    return _suite()[0]


@pytest.fixture(scope="session")
def suite_eval(suite_runs):
    return evals.evaluate_suite(suite_runs)


@pytest.fixture(scope="session")
def suite_eval_v2():
    return _suite(chunker="v2")[1]


@pytest.fixture(scope="session")
def agent_runs():
    return [(c, pipeline.run(c["data"], c["requirements"], title=c["title"], mode="agent")) for c in pipeline.load_suite()]
