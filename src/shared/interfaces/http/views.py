from django.http import Http404
from django.views.generic import TemplateView


class PublicPageView(TemplateView):
    """Static public Cargon page adapter for Rotta Web."""


def _text(*parts):
    return " ".join(parts)


BLOG_ARTICLES = {
    "como-funciona-marketplace-fretes-transportes": {
        "template": "public/blog/como-funciona-marketplace-fretes-transportes.html",
        "title": "Como Funciona um Marketplace de Fretes e Transportes",
        "description": _text(
            "Entenda como marketplaces de fretes conectam empresas,",
            "motoristas e transportadores em uma operação digital mais ágil",
            "e rastreável.",
        ),
        "introduction": _text(
            "As plataformas digitais estão mudando a forma como empresas",
            "encontram capacidade de transporte e como motoristas e",
            "transportadores acessam novas oportunidades. Um marketplace de",
            "fretes conecta essas duas pontas em um ambiente digital, tornando",
            "a operação mais ágil, transparente e rastreável.",
        ),
        "image": "public/cargon/img/blog/ca-blog-1.2.png",
        "topic": "Marketplace de fretes",
    },
    "reduzir-custos-transporte-rodoviario-cargas": {
        "template": "public/blog/reduzir-custos-transporte-rodoviario-cargas.html",
        "title": "Como Reduzir Custos no Transporte Rodoviário de Cargas",
        "description": _text(
            "Veja como planejamento, visibilidade operacional e acesso a",
            "transportadores podem ajudar a reduzir custos no transporte",
            "rodoviário.",
        ),
        "introduction": _text(
            "O transporte rodoviário representa uma parcela significativa dos",
            "custos logísticos de muitas empresas. Melhor planejamento, maior",
            "visibilidade operacional e acesso a uma rede mais ampla de",
            "transportadores podem contribuir para reduzir desperdícios e",
            "melhorar a utilização dos veículos.",
        ),
        "image": "public/cargon/img/blog/ca-blog-1.3.png",
        "topic": "Custos logísticos",
    },
    "rastreamento-cargas-seguranca-transparencia": {
        "template": "public/blog/rastreamento-cargas-seguranca-transparencia.html",
        "title": "Rastreamento de Cargas: Mais Segurança e Transparência na Operação",
        "description": _text(
            "Saiba por que o rastreamento de cargas aumenta segurança, reduz",
            "incertezas e melhora a transparência das operações de transporte.",
        ),
        "introduction": _text(
            "Saber onde está uma carga e acompanhar as principais etapas da",
            "operação reduz incertezas para embarcadores, transportadores e",
            "clientes. O rastreamento digital tornou-se uma ferramenta essencial",
            "para aumentar a segurança e a transparência no transporte.",
        ),
        "image": "public/cargon/img/blog/ca-blog-1.1.png",
        "topic": "Rastreamento",
    },
    "escolher-veiculo-ideal-transporte": {
        "template": "public/blog/escolher-veiculo-ideal-transporte.html",
        "title": "Como Escolher o Veículo Ideal para Cada Tipo de Transporte",
        "description": _text(
            "Conheça fatores que influenciam a escolha do veículo adequado",
            "para cada operação de transporte, como peso, volume e tipo de carga.",
        ),
        "introduction": _text(
            "Peso, volume, dimensões, tipo de mercadoria e condições da operação",
            "influenciam diretamente a escolha do veículo. Selecionar a categoria",
            "adequada ajuda a reduzir custos, aumentar a segurança e evitar",
            "problemas durante o transporte.",
        ),
        "image": "public/cargon/img/blog/ca-blog-1.4.png",
        "topic": "Veículos",
    },
    "motorista-agregado-como-funciona-vantagens": {
        "template": "public/blog/motorista-agregado-como-funciona-vantagens.html",
        "title": "Motorista Agregado: Como Funciona e Quais São as Vantagens",
        "description": _text(
            "Entenda o papel do motorista agregado e como plataformas digitais",
            "podem aproximar profissionais de novas oportunidades de frete.",
        ),
        "introduction": _text(
            "Motoristas agregados exercem papel importante na capacidade",
            "operacional do transporte rodoviário. Plataformas digitais podem",
            "aproximá-los de novas oportunidades de frete e facilitar a gestão",
            "da operação.",
        ),
        "image": "public/cargon/img/blog/ca-blog-1.5.png",
        "topic": "Motoristas",
    },
    "tecnologia-logistica-plataformas-digitais": {
        "template": "public/blog/tecnologia-logistica-plataformas-digitais.html",
        "title": _text(
            "Tecnologia na Logística: Como Plataformas Digitais Estão",
            "Transformando o Transporte",
        ),
        "description": _text(
            "Veja como dados em tempo real, aplicativos móveis, automação e",
            "integrações estão transformando a logística e o transporte.",
        ),
        "introduction": _text(
            "Dados em tempo real, aplicativos móveis, automação e integração de",
            "sistemas estão transformando a logística. Plataformas digitais",
            "permitem conectar participantes que antes dependiam de processos",
            "fragmentados, telefone, mensagens e controles manuais.",
        ),
        "image": "public/cargon/img/blog/ca-blog-1.6.png",
        "topic": "Tecnologia",
    },
    "prova-entrega-digital-pod": {
        "template": "public/blog/prova-entrega-digital-pod.html",
        "title": "Prova de Entrega Digital (POD): O Que É e Por Que Ela É Importante",
        "description": _text(
            "Entenda o que é prova de entrega digital e por que fotos,",
            "assinatura, localização e horário aumentam a rastreabilidade.",
        ),
        "introduction": _text(
            "A prova de entrega digital registra a conclusão de uma operação de",
            "transporte por meio de informações como fotos, assinatura,",
            "localização e horário. Esse processo aumenta a rastreabilidade e",
            "reduz dependência de documentos físicos.",
        ),
        "image": "public/cargon/img/blog/ca-blog-1.7.png",
        "topic": "POD",
    },
    "seguranca-transporte-cargas": {
        "template": "public/blog/seguranca-transporte-cargas.html",
        "title": _text(
            "Segurança no Transporte de Cargas: Boas Práticas para Empresas",
            "e Motoristas",
        ),
        "description": _text(
            "Conheça boas práticas de segurança no transporte de cargas",
            "envolvendo cadastro, documentação, rastreabilidade e acompanhamento.",
        ),
        "introduction": _text(
            "Segurança no transporte envolve pessoas, veículos, informações e",
            "processos. Cadastro adequado, rastreabilidade, documentação e",
            "acompanhamento da operação ajudam a reduzir riscos e melhorar a",
            "confiabilidade da cadeia logística.",
        ),
        "image": "public/cargon/img/blog/ca-blog-1.8.png",
        "topic": "Segurança",
    },
    "futuro-transporte-rodoviario": {
        "template": "public/blog/futuro-transporte-rodoviario.html",
        "title": _text(
            "O Futuro do Transporte Rodoviário: Dados, Automação e Logística",
            "em Tempo Real",
        ),
        "description": _text(
            "Explore como dados, telemetria, automação e plataformas digitais",
            "apontam para o futuro conectado do transporte rodoviário.",
        ),
        "introduction": _text(
            "O transporte rodoviário caminha para operações cada vez mais",
            "conectadas. Dados, telemetria, automação e plataformas digitais",
            "permitem decisões mais rápidas e uma visão mais precisa de toda a",
            "jornada do transporte.",
        ),
        "image": "public/cargon/img/blog/ca-blog-1.9.png",
        "topic": "Futuro do transporte",
    },
}


class BlogArticleView(TemplateView):
    """Controlled static blog article adapter for Rotta Web."""

    def dispatch(self, request, *args, **kwargs):
        self.article = BLOG_ARTICLES.get(kwargs["slug"])
        if self.article is None:
            raise Http404("Blog article not found")
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        return [self.article["template"]]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["article"] = {"slug": self.kwargs["slug"], **self.article}
        return context
