import { http, type ApiResponse } from './http'

export interface NoteListItem {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface NoteList {
  items: NoteListItem[]
  total: number
  page: number
  page_size: number
}

export interface Note {
  id: string
  title: string
  content: string
  created_at: string
  updated_at: string
}

export async function listNotes(page = 1, pageSize = 50): Promise<NoteList> {
  const resp = await http.get<ApiResponse<NoteList>>('/notes', {
    params: { page, page_size: pageSize },
  })
  return resp.data.data
}

export async function getNote(id: string): Promise<Note> {
  const resp = await http.get<ApiResponse<Note>>(`/notes/${id}`)
  return resp.data.data
}

export async function createNote(title: string, content: string): Promise<string> {
  const resp = await http.post<ApiResponse<{ id: string }>>('/notes', { title, content })
  return resp.data.data.id
}

export async function updateNote(id: string, title: string, content: string): Promise<void> {
  await http.put(`/notes/${id}`, { title, content })
}

export async function deleteNote(id: string): Promise<void> {
  await http.delete(`/notes/${id}`)
}
