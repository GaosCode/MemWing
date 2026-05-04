export const controlScope = {
  project_memory_space_id: import.meta.env.VITE_MEMWING_PROJECT_MEMORY_SPACE_ID ?? "project_001",
  group_id: import.meta.env.VITE_MEMWING_GROUP_ID || undefined,
  thread_id: import.meta.env.VITE_MEMWING_THREAD_ID || undefined,
  shared_group_id: import.meta.env.VITE_MEMWING_SHARED_GROUP_ID || undefined,
};
