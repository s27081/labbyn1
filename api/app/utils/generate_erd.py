import os
import sys

sys.path.append(os.getcwd())

try:
    from app.db.models import Base
except ImportError as e:
    print(f"Błąd importu: {e}")
    sys.exit(1)


def generate_dot_manually():
    print("Ręczne generowanie pliku DOT z metadanych...")

    tables = Base.metadata.tables
    dot_lines = [
        "digraph G {",
        '    node [shape=none, fontname="Helvetica"];',
        "    rankdir=LR;",
    ]

    for table_name, table in tables.items():
        label = f'<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0"><TR><TD COLSPAN="2"><B>{table_name}</B></TD></TR>'
        for column in table.columns:
            pk = " (PK)" if column.primary_key else ""
            label += f'<TR><TD ALIGN="LEFT">{column.name}{pk}</TD><TD ALIGN="LEFT">{column.type}</TD></TR>'
        label += "</TABLE>>"

        dot_lines.append(f'    "{table_name}" [label={label}];')

        for column in table.columns:
            for fk in column.foreign_keys:
                target_table = fk.column.table.name
                dot_lines.append(
                    f'    "{table_name}" -> "{target_table}" [label="{column.name}"];'
                )

    dot_lines.append("}")

    with open("schema.dot", "w", encoding="utf-8") as f:
        f.write("\n".join(dot_lines))

    print("\n--- SUKCES! ---")
    print(f"Plik wygenerowany: {os.path.abspath('schema.dot')}")
    print("Wklej zawartość do: https://dreampuf.github.io/GraphvizOnline/")


if __name__ == "__main__":
    generate_dot_manually()
