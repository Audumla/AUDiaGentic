"""Test markdown-it-py for hierarchical section parsing."""

from markdown_it import MarkdownIt


def build_section_tree(tokens):
    """Build a heading tree from markdown-it tokens."""
    root = {"level": 0, "heading": None, "children": []}
    stack = [root]

    for i, token in enumerate(tokens):
        if token.type == "heading_open":
            level = int(token.tag[1])
            # Extract heading text from next inline token
            content = ""
            for next_token in tokens[i + 1 :]:
                if next_token.type == "inline":
                    for child in next_token.children:
                        if child.type == "text":
                            content += child.content
                    break

            node = {"level": level, "heading": content, "children": []}

            # Pop until we find a parent with lower level
            while stack[-1]["level"] >= level and len(stack) > 1:
                stack.pop()

            stack[-1]["children"].append(node)
            stack.append(node)

    return root


def print_tree(node, indent=0):
    if node["heading"]:
        label = f"h{node['level']}: {node['heading']!r}"
        print("  " * indent + label)
    for child in node["children"]:
        print_tree(child, indent + 1)


md = MarkdownIt()

# Test 1: Normal heading hierarchy
text1 = """# Title

## Description

Content.

### Sub-step A

Sub-content A.

### Sub-step B

Sub-content B.

## Steps

Step 1.

#### Step 1 Detail

Detail about step 1.

## Notes

A note."""

print("=== Test 1: Normal heading hierarchy ===")
tokens = md.parse(text1)
tree = build_section_tree(tokens)
print_tree(tree)

# Test 2: Code blocks with headings inside
text2 = """# Title

## Description

Content with a code block:

```markdown
## This is in a code block
Should be ignored.
```

More content.

## Steps

Step 1."""

print("\n=== Test 2: Code blocks (headings should be ignored) ===")
tokens = md.parse(text2)
tree = build_section_tree(tokens)
print_tree(tree)

# Test 3: LLM mistake - using ## instead of ### for sub-sections
text3 = """# Title

## Description

Content.

## Sub-step A

This should probably be a subsection but is at h2 level.

## Steps

Step 1."""

print("\n=== Test 3: LLM mistake (## where ### intended) ===")
tokens = md.parse(text3)
tree = build_section_tree(tokens)
print_tree(tree)
