import sys

from datasets.shikoku_nature_trail import cli, pipeline

if __name__ == "__main__":
    legacy = {"crawl-index", "crawl-details", "download-assets", "download-kml",
              "crawl-all", "verify", "report", "normalize", "export-map"}
    values = {"--data-dir", "--raw-dir", "--output-dir", "--reports-dir",
              "--timeout", "--concurrency", "--delay", "--log-level", "--image"}
    arguments = iter(sys.argv[1:])
    command = None
    for argument in arguments:
        if argument in values:
            next(arguments, None)
        elif not argument.startswith("-"):
            command = argument
            break
    main = cli.main if command in legacy else pipeline.main
    sys.exit(main())