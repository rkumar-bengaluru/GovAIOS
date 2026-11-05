# Task 8 report
Status: DONE. CLI wired (run, verify-audit, audit-ui, doctor, dump, selftest --dev), require_app added, exit-file handling on SystemExit/other exceptions. 85 tests pass with -W error.
Concerns: dump relies on MacDesktop.web_root/window_title not activating Chrome (not verified, not run); test_run_dev_blocks_network patches Runner.__init__ too, so the ordering "block before Runner" is by code, not asserted.
