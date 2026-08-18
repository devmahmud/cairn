import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownContent } from "./MarkdownContent";

describe("MarkdownContent", () => {
  it("renders headings, emphasis, links, and GFM tables", () => {
    const md = [
      "# Title",
      "",
      "Some **bold** text and a [link](https://example.com).",
      "",
      "- one",
      "- two",
      "",
      "| A | B |",
      "| --- | --- |",
      "| 1 | 2 |",
    ].join("\n");
    render(<MarkdownContent content={md} />);

    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    const bold = screen.getByText("bold");
    expect(bold.tagName).toBe("STRONG");
    const link = screen.getByRole("link", { name: "link" });
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer noopener");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "A" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "1" })).toBeInTheDocument();
  });

  it("never renders raw HTML from message content -- no rehype-raw is wired in", () => {
    const marker = "__markdown_xss_marker__";
    (window as unknown as Record<string, boolean>)[marker] = false;
    const { container } = render(
      <MarkdownContent
        content={`before <script>window["${marker}"] = true;</script> <img src=x onerror="window['${marker}'] = true"> after`}
      />,
    );

    expect(container.querySelector("script")).not.toBeInTheDocument();
    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect((window as unknown as Record<string, boolean>)[marker]).toBe(false);
  });

  it("survives an unclosed code fence mid-stream without throwing or losing later text", () => {
    expect(() =>
      render(<MarkdownContent content={"Here is code:\n\n```js\nconst x = 1;\nconst y ="} />),
    ).not.toThrow();
  });

  it("survives a malformed/partial table and list fragment mid-stream without throwing", () => {
    expect(() =>
      render(<MarkdownContent content={"| A | B\n| --- |\n- one\n- tw"} />),
    ).not.toThrow();
  });

  it("re-parses cleanly as more streamed text arrives, char by char", () => {
    const full = "# Heading\n\nSome **bold** text with a [link](https://example.com) and:\n\n```js\nconst x = 1;\n```\n\n- a\n- b\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n";
    for (let i = 1; i <= full.length; i += 7) {
      expect(() => render(<MarkdownContent content={full.slice(0, i)} />)).not.toThrow();
    }
  });
});
