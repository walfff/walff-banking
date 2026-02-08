pipeline {
    agent any

    options {
        ansiColor('xterm')
        timestamps()
        skipDefaultCheckout()
    }

    environment {
        AWS_REGION         = 'us-east-2'
        LAMBDA_FUNCTION    = 'mini-banco-lambda'
        S3_BUCKET          = 'mini-banco-frontend'
        CLOUDFRONT_DIST_ID = 'E2QL6ZDLLSNOF2'
    }

    stages {

        stage('📥 Checkout') {
            steps {
                script {
                    printHeader('CHECKOUT')
                    checkout scm
                    def commitMsg = sh(script: 'git log -1 --pretty=%B', returnStdout: true).trim()
                    def commitHash = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
                    def author = sh(script: 'git log -1 --pretty=%an', returnStdout: true).trim()
                    printSuccess("Commit: ${commitHash} — ${commitMsg}")
                    printInfo("Autor: ${author}")
                }
            }
        }

        stage('🧪 Testes') {
            steps {
                script {
                    printHeader('TESTES')

                    // Verifica arquivos
                    def backendOk = fileExists('backend/lambda_function.py')
                    def frontendOk = fileExists('frontend/index.html')

                    if (backendOk) {
                        printSuccess('backend/lambda_function.py encontrado')
                    } else {
                        printError('backend/lambda_function.py NÃO encontrado')
                        error('Arquivo backend ausente')
                    }

                    if (frontendOk) {
                        printSuccess('frontend/index.html encontrado')
                    } else {
                        printError('frontend/index.html NÃO encontrado')
                        error('Arquivo frontend ausente')
                    }

                    // Valida Python
                    sh(script: '''
                        python3 -c "
import py_compile
py_compile.compile('backend/lambda_function.py', doraise=True)
" 2>&1
                    ''', returnStdout: true)
                    printSuccess('Python: sintaxe válida')

                    // Valida HTML
                    def htmlSize = sh(script: 'wc -c < frontend/index.html', returnStdout: true).trim()
                    printSuccess("HTML: ${htmlSize} bytes")
                }
            }
        }

        stage('⚡ Deploy Lambda') {
            steps {
                script {
                    printHeader('DEPLOY LAMBDA')
                    withCredentials([[$class: 'AmazonWebServicesCredentialsBinding',
                        credentialsId: 'aws-jenkins-credentials']]) {

                        // Empacotar
                        sh 'cd backend && zip -j ../lambda-package.zip lambda_function.py > /dev/null 2>&1'
                        printInfo('Pacote ZIP criado')

                        // Deploy
                        def result = sh(script: '''
                            aws lambda update-function-code \
                                --function-name $LAMBDA_FUNCTION \
                                --zip-file fileb://lambda-package.zip \
                                --region $AWS_REGION \
                                --output text \
                                --query 'CodeSha256' 2>&1
                        ''', returnStdout: true).trim()
                        printSuccess("Lambda atualizada — SHA: ${result.take(16)}...")

                        // Aguardar
                        printInfo('Aguardando Lambda ficar pronta...')
                        sh 'aws lambda wait function-updated --function-name $LAMBDA_FUNCTION --region $AWS_REGION 2>&1'
                        printSuccess('Lambda pronta para uso')
                    }
                }
            }
        }

        stage('🌐 Deploy S3') {
            steps {
                script {
                    printHeader('DEPLOY FRONTEND')
                    withCredentials([[$class: 'AmazonWebServicesCredentialsBinding',
                        credentialsId: 'aws-jenkins-credentials']]) {

                        def result = sh(script: '''
                            aws s3 sync frontend/ s3://$S3_BUCKET/ \
                                --region $AWS_REGION \
                                --delete \
                                --cache-control "max-age=0" 2>&1 | tail -5
                        ''', returnStdout: true).trim()

                        if (result) {
                            printInfo("Arquivos sincronizados")
                        }
                        printSuccess("Frontend enviado para s3://${S3_BUCKET}/")
                    }
                }
            }
        }

        stage('🔄 Invalidar CDN') {
            steps {
                script {
                    printHeader('INVALIDAR CLOUDFRONT')
                    withCredentials([[$class: 'AmazonWebServicesCredentialsBinding',
                        credentialsId: 'aws-jenkins-credentials']]) {

                        def invId = sh(script: '''
                            aws cloudfront create-invalidation \
                                --distribution-id $CLOUDFRONT_DIST_ID \
                                --paths "/*" \
                                --region $AWS_REGION \
                                --output text \
                                --query 'Invalidation.Id' 2>&1
                        ''', returnStdout: true).trim()

                        printSuccess("Cache invalidado — ID: ${invId}")
                        printInfo("Site atualizado em ~30 segundos")
                    }
                }
            }
        }
    }

    post {
        success {
            script {
                echo '\n'
                echo '\033[32m╔══════════════════════════════════════════════╗\033[0m'
                echo '\033[32m║                                              ║\033[0m'
                echo '\033[32m║   ✅  DEPLOY COMPLETO COM SUCESSO!           ║\033[0m'
                echo '\033[32m║   🏦  Walff Banking atualizado               ║\033[0m'
                echo '\033[32m║                                              ║\033[0m'
                echo '\033[32m║   🌐  https://dqkuu9khhhnt5.cloudfront.net   ║\033[0m'
                echo '\033[32m║                                              ║\033[0m'
                echo '\033[32m╚══════════════════════════════════════════════╝\033[0m'
                echo '\n'
            }
        }
        failure {
            script {
                echo '\n'
                echo '\033[31m╔══════════════════════════════════════════════╗\033[0m'
                echo '\033[31m║                                              ║\033[0m'
                echo '\033[31m║   ❌  DEPLOY FALHOU!                         ║\033[0m'
                echo '\033[31m║   📋  Verifique os logs acima                ║\033[0m'
                echo '\033[31m║                                              ║\033[0m'
                echo '\033[31m╚══════════════════════════════════════════════╝\033[0m'
                echo '\n'
            }
        }
    }
}

// ═══════════════════════════════════════
// Funções auxiliares para logs bonitos
// ═══════════════════════════════════════

def printHeader(String title) {
    echo "\n\033[36m═══════════════════════════════════════\033[0m"
    echo "\033[36m  ${title}\033[0m"
    echo "\033[36m═══════════════════════════════════════\033[0m"
}

def printSuccess(String msg) {
    echo "\033[32m  ✅ ${msg}\033[0m"
}

def printError(String msg) {
    echo "\033[31m  ❌ ${msg}\033[0m"
}

def printInfo(String msg) {
    echo "\033[33m  ℹ️  ${msg}\033[0m"
}