import os
from collections import defaultdict, Counter
from urllib.parse import quote
import re
import logging

from mkdocs.utils import warning_filter
from mkdocs.plugins import BasePlugin


LOG = logging.getLogger("mkdocs.plugins." + __name__)
LOG.addFilter(warning_filter)

# For Regex, match groups are:
#       0: Whole markdown link e.g. [Alt-text](url)
#       1: Alt text
#       2: Full URL e.g. url + hash anchor
#       3: Filename e.g. filename.md
#       4: File extension e.g. .md, .png, etc.
#       5. hash anchor e.g. #my-sub-heading-link

AUTOLINK_RE = r'(?:\!\[\]|\[([^\]]+)\])\((([^)/]+\.(md|png|jpg|jpeg|bmp|gif))(#[^)]*)*)\)'


class AutoLinkReplacer:
    def __init__(self, base_docs_dir, abs_page_path, filename_to_abs_path, missing_filenames):
        self.base_docs_dir = base_docs_dir
        self.abs_page_path = abs_page_path
        self.filename_to_abs_path = filename_to_abs_path
        self.missing_filenames = missing_filenames

    def __call__(self, match):
        # Name of the file
        filename = match.group(3).strip()

        # Absolute path to the directory of the linker
        abs_linker_dir = os.path.dirname(self.abs_page_path)

        # Look up the filename in the filename to absolute path lookup dict
        try:
            abs_link_path = self.filename_to_abs_path[filename]
        except KeyError:
            rel_page_path = os.path.relpath(self.abs_page_path, self.base_docs_dir)
            self.missing_filenames[filename][rel_page_path] += 1
            LOG.warning(
                "AutoLinksPlugin unable to find %s in directory %s",
                filename,
                self.base_docs_dir,
            )
            return match.group(0)

        rel_link_path = quote(os.path.relpath(abs_link_path, abs_linker_dir))

        # Construct the return link by replacing the filename with the relative path to the file
        return match.group(0).replace(match.group(3), rel_link_path)


class AutoLinksPlugin(BasePlugin):
    def __init__(self):
        self.filename_to_abs_path = None
        self.missing_filenames = defaultdict(Counter)
        self.duplicate_filenames = defaultdict(list)

    def on_page_markdown(self, markdown, page, config, files, **kwargs):
        # Getting the root location of markdown source files
        base_docs_dir = config["docs_dir"]

        # Initializes the filename lookiup dict if it hasn't already been initialized
        if self.filename_to_abs_path is None:
            self.init_filename_to_abs_path(files, base_docs_dir)

        # Getting the page path that we are linking from
        abs_page_path = page.file.abs_src_path

        # Look for matches and replace
        markdown = re.sub(
            AUTOLINK_RE,
            AutoLinkReplacer(base_docs_dir, abs_page_path, self.filename_to_abs_path, self.missing_filenames),
            markdown,
        )

        return markdown

    def on_post_build(self, config):
        # TODO: extract to mkdocs config
        report_path = "mkdocs-autolinks-plugin-report.md"
        with open(report_path, "w") as f:
            f.write(self.generate_report())
            LOG.info("Wrote AutoLinksPlugin report to '%s'", report_path)

    def generate_report(self):
        duplicate_filenames_strs = []
        for filename in sorted(self.duplicate_filenames):
            paths = ', '.join(f"`{p}`" for p in self.duplicate_filenames[filename])
            duplicate_filenames_strs.append(f"- [ ] {filename}, at {paths}")
        duplicate_filenames_str = "\n".join(
            duplicate_filenames_strs
        )

        missing_filenames_strs = []
        for filename in sorted(self.missing_filenames):
            ref_strs = []
            for ref_path in self.missing_filenames[filename]:
                occurences = self.missing_filenames[filename][ref_path]
                ref_strs.append(f"  - `{ref_path}` ({occurences} occurences)")
            refs_str = "\n".join(ref_strs)
            num_files = len(self.missing_filenames[filename])
            missing_filenames_strs.append(f"- [ ] {filename}, in {num_files} file(s)\n{refs_str}")
        missing_filenames_str = "\n".join(missing_filenames_strs)

        return f"""\
# AutoLinksPlugin report

## Duplicate filenames

{duplicate_filenames_str}

## Missing filenames

{missing_filenames_str}
"""
              

    def init_filename_to_abs_path(self, files, docs_dir):
        self.filename_to_abs_path = {}
        for file_ in files:
            filename = os.path.basename(file_.abs_src_path)

            if filename in self.filename_to_abs_path:
                if len(self.duplicate_filenames[filename]) == 0:
                    self.duplicate_filenames[filename].append(
                        os.path.relpath(self.filename_to_abs_path[filename], docs_dir)
                    )
                
                self.duplicate_filenames[filename].append(file_.src_path)
                LOG.warning(
                    "Duplicate filename: '%s' exists at both '%s' and '%s'",
                    filename,
                    file_.abs_src_path,
                    self.filename_to_abs_path[filename],
                )
                continue

            self.filename_to_abs_path[filename] = file_.abs_src_path
