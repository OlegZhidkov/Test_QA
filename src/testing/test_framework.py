"""Run one ammeter end to end: sample, analyze, archive and report."""
import logging
from dataclasses import replace
from pathlib import Path

from src.testing.AmmeterTester import AmmeterTester
from src.testing.analysis import out_of_range
from src.testing.models import RunResult
from src.testing.report import format_run_report
from src.utils.config import DEFAULT_CONFIG_PATH, FrameworkConfig, SamplingPlan, load_config
from src.utils.logger import TestLogger
from src.utils.results import new_run_id, save_run


class AmmeterTestFramework:
    """Runs the configured ammeters and archives each run."""

    def __init__(self, config_path: str | Path = DEFAULT_CONFIG_PATH,
                 config: FrameworkConfig | None = None):
        """Use `config` if given, otherwise load and validate the file at `config_path`."""
        self.config = config if config is not None else load_config(config_path)

    def tester(self, name: str, logger: logging.Logger | None = None) -> AmmeterTester:
        """A tester for the named ammeter."""
        return AmmeterTester.from_config(self.config, name, logger)

    def run_test(self, name: str, plan: SamplingPlan | None = None) -> RunResult:
        """Sample one ammeter, analyze, archive and log the report."""
        settings = self.config.settings_for(name)
        plan = plan or self.config.sampling
        run_id = new_run_id(name)
        run_log = TestLogger(name, log_dir=self.config.results_dir / "logs", run_id=run_id)
        try:
            tester = self.tester(name, run_log.logger)
            sample = tester.sample(plan)
            parameters = {
                "count": plan.count, "duration_s": plan.duration_s,
                "frequency_hz": plan.frequency_hz, "interval_s": plan.interval_s,
                "request_timeout_s": self.config.request_timeout_s,
                "host": settings.host, "port": settings.port,
                "command": settings.command.decode("utf-8"),
            }
            result = RunResult(
                run_id, name, parameters, settings.expected_range, sample,
                tester.analyze(sample.readings),
                tuple(out_of_range(sample.readings, settings.expected_range)))
            path = save_run(result.to_dict(), self.config.results_dir)
            result = replace(result, archive_path=path)
            run_log.info(format_run_report(result, self.config.metrics))
            return result
        finally:
            run_log.close()

    def run_all(self) -> dict[str, RunResult]:
        """Run every configured ammeter, in config order."""
        return {name: self.run_test(name) for name in self.config.ammeters}
