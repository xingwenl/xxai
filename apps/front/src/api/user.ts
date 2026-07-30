import { http } from '@/lib/http'

export type Paginated<T> = {
  items: T[]
  total: number
  page: number
  pageSize: number
  totalPage: number
}

export type RoleSummary = {
  id: number
  code: string
  name: string
}

export type CurrentUser = {
  id: number
  name: string
  email: string
  account: string
  is_active: boolean
  created_at: string
  updated_at: string
  roles: RoleSummary[]
}

export type SystemUser = CurrentUser

export type ListUsersParams = {
  page?: number
  pageSize?: number
  name?: string
  email?: string
}

export type CreateUserInput = {
  name: string
  email: string
  account: string
  password: string
  role_ids: number[]
}

export type UpdateUserInput = {
  name?: string
  email?: string
  account?: string
  is_active?: boolean
  role_ids?: number[]
}

export async function getCurrentUser(): Promise<CurrentUser | null> {
  const { data } = await http.get<CurrentUser | null>('/auth/me')
  return data
}

export async function getSystemUsers(
  params: ListUsersParams = {}
): Promise<Paginated<SystemUser>> {
  const { data } = await http.get<BackendUserPage>('/users', {
    params: {
      page: params.page,
      page_size: params.pageSize,
      name: params.name,
      email: params.email,
    },
  })
  return normalizePage(data)
}

export async function createSystemUser(
  input: CreateUserInput
): Promise<SystemUser> {
  const { data } = await http.post<SystemUser>('/users', input)
  return data
}

export async function updateSystemUser(
  id: number,
  input: UpdateUserInput
): Promise<SystemUser> {
  const { data } = await http.patch<SystemUser>(`/users/${id}`, input)
  return data
}

export async function deleteSystemUser(id: number): Promise<void> {
  await http.delete(`/users/${id}`)
}

type BackendUserPage = {
  page_no: number
  page_size: number
  items: SystemUser[]
  total: number
  pages: number
}

function normalizePage(page?: BackendUserPage | null): Paginated<SystemUser> {
  return {
    items: page?.items ?? [],
    total: Number(page?.total ?? 0),
    page: Number(page?.page_no ?? 1),
    pageSize: Number(page?.page_size ?? 20),
    totalPage: Number(page?.pages ?? 1),
  }
}
