# Rotta 116 Public Site

The public site presents Rotta 116 as a digital transportation marketplace. It connects clients and shippers that need to move cargo with drivers, agregados, carriers, and transportation partners that provide vehicle capacity.

## Official Routes

- `/` - Home
- `/sobre/` - Sobre Nós
- `/servicos/` - Soluções de Transporte
- `/blog/` - Conteúdo sobre Transporte e Logística
- `/contato/` - Contato
- `/solucoes/` - Soluções and cases of use, reused from the former Projects visual template
- `/app/` - platform entry point, relying on the backoffice authentication redirect

The public navigation remains intentionally simple: Home, Sobre Nós, Serviços, Blog, Contato, and Entrar.

## Editorial Direction

Cargon remains the visual adapter for the public site. The rendered public content must speak as Rotta 116, not as a traditional carrier with its own fleet. Content must distinguish current institutional presentation from planned platform features using terms such as planned, future, or being prepared.

## Official Pages

- `templates/public/home.html`: explains the marketplace, the two sides of the network, vehicle categories, customer flow, driver flow, monitoring, companies, and final CTAs.
- `templates/public/pages/about.html`: explains the problem, proposal, vision, and marketplace model.
- `templates/public/pages/service.html`: presents transportation solutions and links to solutions by operation.
- `templates/public/pages/projects.html`: reused as `/solucoes/`, with cases of use instead of Projects.
- `templates/public/pages/blog.html`: positions future editorial content about transportation and logistics.
- `templates/public/pages/contact.html`: organizes contact by audience without pretending that the form submits an operational request.

## Reference Templates

The alternate Cargon indexes, service variations, blog variations, team, FAQ, pricing, testimonials, and 404 demo templates remain in the repository as reference material. They are not part of the official navigation and must not be treated as public product promises.

## Avoided Claims

The public site must not publish invented metrics, fake testimonials, client logos, pricing tables, certifications, national availability, fleet ownership, or operational features that are not implemented yet.
