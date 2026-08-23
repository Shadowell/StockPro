import { Navigate, useLocation } from 'react-router-dom'
import { resolveHiddenWorkspace } from '../shell/workbench'
import UnavailableWorkspace from './rebuild/UnavailableWorkspace'

export default function UnknownWorkspace() {
  const location = useLocation()
  const hidden = resolveHiddenWorkspace(location.pathname)

  if (!hidden || hidden.redirect) {
    return <Navigate to={hidden?.ownerRoute || '/'} replace />
  }

  return (
    <UnavailableWorkspace
      state={{
        title: hidden.title,
        description: hidden.description,
        ownerRoute: hidden.ownerRoute,
        status: hidden.kind,
      }}
    />
  )
}
