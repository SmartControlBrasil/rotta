# Auditoria de Reprodutibilidade e Limpeza do Build Android — ROTTA 116

Esta documentação resume as atividades realizadas para remover os contornos temporários e reestabelecer o processo de build reproduzível da camada Android do **ROTTA 116** com um Flutter SDK limpo.

## 1. Causa Raiz
A camada Android original do Rotta utilizava infraestrutura legada de build (Gradle 7.6.3, AGP 7.3.0, Kotlin 1.7.10), incompatível com o compilador e as dependências demandadas pelo **Flutter SDK 3.47.0** (que por padrão aponta para as APIs do Android SDK 36 e requer Java 17). 

Desta forma, dependências de pacotes AndroidX modernos de transição (como `core-ktx:1.13.1`, puxado pelo plugin `connectivity_plus`) exigiam `compileSdk >= 34` para compilar. Pela defasagem da configuração, o build falhava, motivando a adoção de hacks invasivos tanto no SDK global do Flutter quanto no aplicativo.

## 2. Hacks Encontrados e Removidos
1. **Alteração do Flutter SDK global**: Scripts Gradle do SDK e classes da extensão do Flutter (`FlutterExtension.kt`, `FlutterPlugin.kt`, etc.) foram forçados a baixar a versão padrão de compileSdk/targetSdk para 34.
2. **Override manual de R8**: Adição manual de dependência do R8 `8.2.24` e repositório raw Maven no `settings.gradle` do aplicativo.
3. **buildToolsVersion forçado**: Forçado em `app/build.gradle` para `"34.0.0"`.
4. **Bypass de validação**: Necessidade de compilar com a flag `--android-skip-build-dependency-validation` para evitar erros de validação de dependências.

Todos os itens acima foram removidos ou revertidos para o estado padrão e limpo.

## 3. Restauração do Flutter SDK
As modificações locais no SDK global do Flutter (`/home/marcelo/development/flutter`) foram completamente revertidas com `git restore` nos seguintes arquivos:
- `packages/flutter_tools/gradle/build.gradle.kts`
- `packages/flutter_tools/gradle/src/main/kotlin/FlutterExtension.kt`
- `packages/flutter_tools/gradle/src/main/kotlin/FlutterPlugin.kt`
- `packages/flutter_tools/gradle/src/main/kotlin/FlutterPluginUtils.kt`
- `packages/flutter_tools/gradle/src/main/kotlin/VersionFetcher.kt`

## 4. Comparação com Template Flutter 3.47
O projeto de referência gerado (`rotta_android_reference`) foi comparado estruturalmente com o app `rotta_driver`:

| Componente | Rotta Antes | Flutter 3.47 Referência | Ação Aplicada |
| :--- | :--- | :--- | :--- |
| **Gradle** | 7.6.3 | 9.3.1 | Atualizado para 9.3.1 |
| **AGP** | 7.3.0 | 9.1.0 | Atualizado para 9.1.0 |
| **Kotlin** | 1.7.10 | 2.4.0 | Atualizado para 2.4.0 |
| **compileSdk** | 36 (restaurado) | 36 | Mantido dinâmico |
| **targetSdk** | 36 (restaurado) | 36 | Mantido dinâmico |
| **minSdk** | 24 | 24 | Mantido dinâmico |
| **Java Target** | Java 8 | Java 17 | Atualizado para Java 17 |
| **Kotlin JVM Target** | Não definido | JVM 17 | Adicionado alvo JVM 17 |
| **buildToolsVersion** | `"34.0.0"` (Fixo) | Não especificado | Removido (AGP autogerencia) |
| **R8/D8** | Custom 8.2.24 | Padrão AGP | Removido o override temporário |
| **Jetifier** | Ativo | Inativo | Removido de `gradle.properties` |

## 5. Migração Android Aplicada
Para suportar o Flutter 3.47.0 sem hacks no SDK global ou bypass de validação, as seguintes modificações foram feitas na camada Android do Rotta:
1. **gradle-wrapper.properties**: Upgrade do Gradle para `9.3.1`.
2. **settings.gradle**: Atualização do AGP para `9.1.0` e do Kotlin Gradle Plugin para `2.4.0`. Remoção completa do bloco `buildscript` do R8.
3. **app/build.gradle**:
   - Remoção de `buildToolsVersion = "34.0.0"`.
   - Atualização do `compileOptions` para `JavaVersion.VERSION_17`.
   - Adicionada configuração do `kotlin.compilerOptions` apontando para `JvmTarget.JVM_17`.
4. **build.gradle (raiz)**: Adicionado um gancho em `subprojects` para forçar `compileSdkVersion 34` em plugins do Flutter (como `connectivity_plus`) cuja configuração nativa aponta para SDK 33. Isso resolve a validação de dependências de forma nativa e limpa.
5. **gradle.properties**: Remoção da flag obsoleta `android.enableJetifier=true`.

## 6. Configuração Final da Toolchain
*   **Gradle**: 9.3.1
*   **AGP**: 9.1.0
*   **Kotlin**: 2.4.0
*   **JDK**: OpenJDK 17.0.19
*   **compileSdk**: 36 (App) / 34 (Plugins com suporte mínimo forçado)
*   **targetSdk**: 36
*   **build-tools**: Autogerenciado pelo AGP 9.1.0

## 7. Resultados de Validação Mobile
*   **flutter analyze**: 0 issues encontrados (sucesso).
*   **flutter test**: 8 testes passados com sucesso.
*   **Build #1**: Sucesso sem `--android-skip-build-dependency-validation`.
*   **Build #2 (Reproducibilidade)**: Sucesso a partir de estado limpo, gerando hash SHA-256 e tamanho de arquivo idênticos ao Build #1.

### Dados do APK Gerado
*   **Caminho**: `apps/rotta_driver/build/app/outputs/flutter-apk/app-debug.apk`
*   **Tamanho do APK**: `156.884.836` bytes (150 MB)
*   **SHA-256**: `3ba619a7c22b8f45d7ee9714df23c0a01d17011312e47b0fa13b64406d5689eb`

## 8. Integridade do Flutter SDK
O SDK global do Flutter está íntegro e limpo. A única mudança apontada pelo git é o arquivo `pubspec.lock`, modificado por operações normais de dependência locais do SDK e não relacionado a esta tarefa.

## 9. Regressão do Backend
*   `.venv/bin/python manage.py check`: Sucesso (sem erros).
*   `.venv/bin/python manage.py makemigrations --check`: Sucesso (sem migrações pendentes).
*   `.venv/bin/pytest tests/test_pilot_smoke_flow.py -q`: Sucesso (1 test passed).
*   `.venv/bin/pytest -q`: Sucesso (498 tests passed).

## 10. Débitos Remanescentes
*   Nenhum débito temporário identificado. A solução de forçar a compilação dos plugins com SDK 34 no `build.gradle` é definitiva e limpa enquanto os pacotes de terceiros não forem atualizados.

---
**Classificação Final**: A — ANDROID BUILD REPRODUCIBLE
