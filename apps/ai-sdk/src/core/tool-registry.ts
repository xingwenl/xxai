import type { ToolDefinition } from './types'

export class ToolRegistry {
  private tools: Map<string, ToolDefinition> = new Map()

  registerTool(tool: ToolDefinition): void {
    this.tools.set(tool.name, tool)
  }

  registerTools(tools: ToolDefinition[]): void {
    tools.forEach((tool) => this.registerTool(tool))
  }

  unregisterTool(name: string): void {
    this.tools.delete(name)
  }

  getTool(name: string): ToolDefinition | undefined {
    return this.tools.get(name)
  }

  getToolNames(): string[] {
    return Array.from(this.tools.keys())
  }

  getTools(): ToolDefinition[] {
    return Array.from(this.tools.values())
  }

  clearCustomTools(): void {
    this.tools.clear()
  }
}
