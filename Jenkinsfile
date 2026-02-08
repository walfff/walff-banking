pipeline {
    agent any
    options {
        ansiColor('xterm')
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
                echo '🔄 Baixando código do repositório...'
                checkout scm
            }
        }

        stage('🧪 Testes') {
            steps {
                echo '🧪 Validando arquivos...'
                sh '''
                    # Verifica se os arquivos existem
                    test -f backend/lambda_function.py || exit 1
                    test -f frontend/index.html || exit 1

                    # Verifica sintaxe Python
                    python3 -c "
import py_compile
py_compile.compile('backend/lambda_function.py', doraise=True)
print('✅ Python: sintaxe OK')
"

                    # Verifica se o HTML não está vazio
                    if [ $(wc -c < frontend/index.html) -lt 100 ]; then
                        echo '❌ index.html parece vazio!'
                        exit 1
                    fi
                    echo '✅ HTML: arquivo válido'
                '''
            }
        }

        stage('⚡ Deploy Lambda') {
            steps {
                echo '⚡ Atualizando código da Lambda...'
                withCredentials([[$class: 'AmazonWebServicesCredentialsBinding',
                    credentialsId: 'aws-jenkins-credentials']]) {
                    sh '''
                        # Empacota o código Python em ZIP
                        cd backend
                        zip -j ../lambda-package.zip lambda_function.py
                        cd ..

                        # Atualiza a função Lambda
                        aws lambda update-function-code \
                            --function-name $LAMBDA_FUNCTION \
                            --zip-file fileb://lambda-package.zip \
                            --region $AWS_REGION

                        echo '✅ Lambda atualizada com sucesso!'

                        # Aguarda a atualização finalizar
                        aws lambda wait function-updated \
                            --function-name $LAMBDA_FUNCTION \
                            --region $AWS_REGION

                        echo '✅ Lambda pronta para uso!'
                    '''
                }
            }
        }

        stage('🌐 Deploy Frontend (S3)') {
            steps {
                echo '🌐 Enviando frontend para o S3...'
                withCredentials([[$class: 'AmazonWebServicesCredentialsBinding',
                    credentialsId: 'aws-jenkins-credentials']]) {
                    sh '''
                        # Sincroniza o frontend com o S3
                        aws s3 sync frontend/ s3://$S3_BUCKET/ \
                            --region $AWS_REGION \
                            --delete \
                            --cache-control "max-age=0"

                        echo '✅ Frontend enviado para S3!'
                    '''
                }
            }
        }

        stage('🔄 Invalidar CloudFront') {
            steps {
                echo '🔄 Invalidando cache do CloudFront...'
                withCredentials([[$class: 'AmazonWebServicesCredentialsBinding',
                    credentialsId: 'aws-jenkins-credentials']]) {
                    sh '''
                        aws cloudfront create-invalidation \
                            --distribution-id $CLOUDFRONT_DIST_ID \
                            --paths "/*" \
                            --region $AWS_REGION

                        echo '✅ Cache invalidado! Site atualizado.'
                    '''
                }
            }
        }
    }

    post {
        success {
            echo '''
            ╔══════════════════════════════════════╗
            ║  ✅ DEPLOY COMPLETO COM SUCESSO!     ║
            ║  🏦 Walff Banking atualizado         ║
            ╚══════════════════════════════════════╝
            '''
        }
        failure {
            echo '''
            ╔══════════════════════════════════════╗
            ║  ❌ DEPLOY FALHOU!                   ║
            ║  Verifique os logs acima             ║
            ╚══════════════════════════════════════╝
            '''
        }
    }
}