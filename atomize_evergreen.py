"""
Evergreen Lincoln Logs Modularizer Script
Extracts atomized modular "Lincoln Log" sub-notes from evergreen vault notes.
"""

import os
import sys
import re
import argparse

def parse_frontmatter(content):
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[1], parts[2]
    return "", content

def atomize_evergreen_note(file_path, output_dir=None, dry_run=False):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    fm_raw, body = parse_frontmatter(content)
    
    # Check if evergreen status or requested
    if "status: evergreen" not in fm_raw.lower() and "status: \"evergreen\"" not in fm_raw.lower():
        print(f"[Warning] Note {os.path.basename(file_path)} does not have status: evergreen. Proceeding as requested.")

    if not output_dir:
        output_dir = os.path.dirname(file_path)

    # Split body by H2 headings to identify candidates for Lincoln Log atomization
    sections = re.split(r'\n(?=##\s+)', body)
    
    parent_title = os.path.splitext(os.path.basename(file_path))[0]
    modified_body_sections = [sections[0]] # Main introduction stays in parent note
    extracted_notes = []

    for section in sections[1:]:
        lines = section.strip().split("\n")
        header_line = lines[0]
        section_title = header_line.replace("##", "").strip()
        
        # Clean title for filename
        clean_title = re.sub(r'[\\/*?:"<>|]', '', section_title)
        clean_title = f"{parent_title} - {clean_title}"
        atom_filename = f"{clean_title}.md"
        atom_path = os.path.join(output_dir, atom_filename)
        
        atom_content = (
            "---\n"
            f"type: lincoln_log_atom\n"
            f"parent_note: \"[[{parent_title}]]\"\n"
            f"status: stub\n"
            "---\n\n"
            f"# {section_title}\n\n"
            f"> [!INFO] **Lincoln Log Atomized Concept**\n"
            f"> Extracted from parent evergreen note: [[{parent_title}]]\n\n"
            + "\n".join(lines[1:]).strip() + "\n"
        )
        
        extracted_notes.append((atom_path, atom_content, clean_title))
        
        # Replace section in parent note with transclusion transcluding the Lincoln Log
        transclusion = f"\n\n## {section_title}\n![[{clean_title}]]\n"
        modified_body_sections.append(transclusion)

    if dry_run:
        print(f"[Dry Run] Would create {len(extracted_notes)} Lincoln Log sub-notes for '{parent_title}':")
        for atom_path, _, clean_title in extracted_notes:
            print(f"  - {clean_title} -> {atom_path}")
        return True

    # Write out extracted atomic sub-notes
    for atom_path, atom_content, _ in extracted_notes:
        with open(atom_path, "w", encoding="utf-8") as f:
            f.write(atom_content)
        print(f"Created Lincoln Log atom: {os.path.basename(atom_path)}")

    # Update parent note content with transclusions
    new_parent_content = (
        "---\n" + fm_raw.strip() + "\n---\n" +
        "\n".join(modified_body_sections)
    )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_parent_content)

    print(f"Updated parent evergreen note: {file_path} with transcluded Lincoln Logs.")
    return True

def main():
    parser = argparse.ArgumentParser(description="Evergreen Note Lincoln Logs Modularizer")
    parser.add_argument("--file", required=True, help="Target markdown note path")
    parser.add_argument("--output-dir", help="Output directory for extracted sub-notes")
    parser.add_argument("--dry-run", action="store_true", help="Print proposed actions without writing")
    args = parser.parse_args()

    atomize_evergreen_note(args.file, output_dir=args.output_dir, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
