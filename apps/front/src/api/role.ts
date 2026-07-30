import { http } from '@/lib/http'
import type { Paginated, RoleSummary } from './user'

// 旧模板角色页面仍使用这一组类型和接口，暂时保留兼容性。
export type SystemRole = {
  id: number
  title: string
  memo?: string | null
  menu_ids?: string | null
  enabled?: number
  create_by?: string | null
  update_by?: string | null
  create_time?: string
  update_time?: string
}

export type ListRolesParams = {
  page?: number
  pageSize?: number
  title?: string
}

export type UpsertRoleInput = {
  title: string
  memo?: string
  menu_ids?: string
}

export async function getSystemRoles(
  params: ListRolesParams = {}
): Promise<Paginated<SystemRole>> {
  const { data } = await http.get<Paginated<SystemRole>>('/api/role', {
    params,
  })
  return normalizePage(data)
}

export async function getSystemRole(id: number): Promise<SystemRole> {
  const { data } = await http.get<SystemRole>(`/api/role/${id}`)
  return data
}

export async function createSystemRole(
  input: UpsertRoleInput
): Promise<SystemRole> {
  const { data } = await http.post<SystemRole>('/api/role', input)
  return data
}

export async function updateSystemRole(
  id: number,
  input: UpsertRoleInput
): Promise<SystemRole> {
  const { data } = await http.put<SystemRole>(`/api/role/${id}`, input)
  return data
}

export async function deleteSystemRole(
  id: number
): Promise<{ id: number; deleted: boolean }> {
  const { data } = await http.delete<{ id: number; deleted: boolean }>(
    `/api/role/${id}`
  )
  return data
}

export type UserRole = RoleSummary & {
  description?: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type Role = UserRole

export type ListRoleParams = {
  page?: number
  pageSize?: number
  name?: string
  code?: string
}

export type CreateRoleInput = {
  code: string
  name: string
  description?: string
}

export type UpdateRoleInput = CreateRoleInput & {
  is_active: boolean
}

export async function listRoles(
  params: ListRoleParams = {}
): Promise<Paginated<Role>> {
  const { data } = await http.get<BackendRolePage>('/roles', {
    params: {
      page: params.page,
      page_size: params.pageSize,
      name: params.name,
      code: params.code,
    },
  })
  return normalizeBackendRolePage(data)
}

export async function createRole(input: CreateRoleInput): Promise<Role> {
  const { data } = await http.post<Role>('/roles', input)
  return data
}

export async function updateRole(
  id: number,
  input: UpdateRoleInput
): Promise<Role> {
  const { data } = await http.patch<Role>(`/roles/${id}`, input)
  return data
}

export async function deleteRole(id: number): Promise<void> {
  await http.delete(`/roles/${id}`)
}

export async function getUserRoles(): Promise<Paginated<UserRole>> {
  const { data } = await http.get<BackendRolePage>('/roles')
  return normalizeBackendRolePage(data)
}

type BackendRolePage = {
  page_no: number
  page_size: number
  items: UserRole[]
  total: number
  pages: number
}

function normalizeBackendRolePage(
  page?: BackendRolePage | null
): Paginated<UserRole> {
  return {
    items: page?.items ?? [],
    total: Number(page?.total ?? 0),
    page: Number(page?.page_no ?? 1),
    pageSize: Number(page?.page_size ?? 20),
    totalPage: Number(page?.pages ?? 1),
  }
}

function normalizePage<T>(page?: Paginated<T> | null): Paginated<T> {
  return {
    items: page?.items ?? [],
    total: Number(page?.total ?? 0),
    page: Number(page?.page ?? 1),
    pageSize: Number(page?.pageSize ?? 20),
    totalPage: Number(page?.totalPage ?? 0),
  }
}
