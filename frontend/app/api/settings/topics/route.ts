import { NextRequest } from 'next/server'
import { proxyTopics } from './proxy'

export async function GET(request: NextRequest) { return proxyTopics(request, 'GET') }
export async function POST(request: NextRequest) { return proxyTopics(request, 'POST') }
