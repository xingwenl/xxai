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

  validate(name: string, params: unknown): void {
    const tool = this.tools.get(name)
    if (!tool) throw new Error('host_tool_not_registered')
    const schema = tool.inputSchema as Record<string, any>
    if (schema.type && schema.type !== 'object') throw new Error('host_tool_schema_invalid')
    if (typeof params !== 'object' || params === null || Array.isArray(params)) {
      throw new Error('host_tool_arguments_invalid')
    }
    const object = params as Record<string, unknown>
    for (const required of (schema.required || []) as string[]) {
      if (!(required in object)) throw new Error('host_tool_arguments_invalid')
    }
    for (const [key, rawDefinition] of Object.entries(schema.properties || {})) {
      const definition = rawDefinition as { type?: string; enum?: unknown[] }
      if (!(key in object)) continue
      const value = object[key]
      if (definition.type === 'string' && typeof value !== 'string') throw new Error('host_tool_arguments_invalid')
      if (definition.type === 'number' && typeof value !== 'number') throw new Error('host_tool_arguments_invalid')
      if (definition.type === 'boolean' && typeof value !== 'boolean') throw new Error('host_tool_arguments_invalid')
      if (definition.enum && !(definition.enum as unknown[]).includes(value)) throw new Error('host_tool_arguments_invalid')
    }
  }

  clearCustomTools(): void {
    this.tools.clear()
  }
}
