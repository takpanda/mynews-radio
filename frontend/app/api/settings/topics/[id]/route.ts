import { NextRequest } from 'next/server'
import { proxyTopics } from '../proxy'

type Context = { params: Promise<{ id: string }> }

export async function PUT(request: NextRequest, { params }: Context) { return proxyTopics(request, 'PUT', (await params).id) }
export async function DELETE(request: NextRequest, { params }: Context) { return proxyTopics(request, 'DELETE', (await params).id) }
