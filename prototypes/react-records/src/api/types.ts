export type Status = 'ok' | 'low_confidence' | 'failed'
export interface Reading { id:number; timestamp:string; device:string; inspection:string; status:Status; value:number | null; version:string; image:string }
export interface Filters { inspection:string; device:string; start:string; end:string }
