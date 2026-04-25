# Frontend and Full Docker Checklist

## Status
- [x] React frontend scaffold exists.
- [x] Contract overview, detail, milestone, workflow, query, wiki, graph, and health screens exist.
- [x] Frontend Docker image exists.
- [x] Nginx serves the built frontend.
- [x] Frontend routes to backend APIs.
- [ ] Final UX polish and full end-to-end manual verification remain.

## API Contract
- [x] Use real backend API responses.
- [x] Consume contracts, milestones, workflow, query, wiki, and graph endpoints.
- [x] Surface citations in the UI.
- [x] Show validation warnings and conflicting clauses.

## Layout
- [x] Fixed sidebar navigation.
- [x] Dense dashboard-style surface.
- [x] Right-side citation drawer.
- [x] Desktop and mobile responsive behavior.

## Pages
- [x] Contract Overview page.
- [x] Contract Detail page.
- [x] Milestone Detail page.
- [x] Payment Workflow page.
- [x] Query page with chat memory.
- [x] Wiki page with markdown pages.
- [x] Knowledge Graph page with SVG render.
- [x] System Health page.

## Workflow
- [x] Show pending acceptance, accepted, payment requested, and paid states.
- [x] Allow acceptance input.
- [x] Allow payment request input.
- [x] Allow payment logging input.
- [x] Refresh financial totals after workflow changes.

## Docker
- [x] Build frontend in a Node stage.
- [x] Serve production files through Nginx.
- [x] Proxy `/api/*` to backend in production.
- [x] Expose port `5173` for local use.
- [x] Include frontend in `docker-compose.yml`.
- [x] Keep Ollama host-native.

## Testing
- [x] Frontend build passes.
- [x] Backend test suite passes.
- [ ] Add UI automation if final grading requires browser-level verification.

## Finalization
- [ ] Capture screenshots or short video.
- [ ] Verify the full Docker compose flow manually.
- [ ] Bundle the final submission artifacts.
