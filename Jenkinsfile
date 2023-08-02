@Library('art-ci-toolkit@master') _

pipeline {
    agent {
        docker {
            image "openshift-art/art-ci-toolkit:latest"
            alwaysPull true
            args "-e http_proxy -e https_proxy -e no_proxy -e HTTP_PROXY -e HTTPS_PROXY -e NO_PROXY --entrypoint=''"
        }
    }
    stages {
        stage("Publish Coverage Report") {
            steps {
                catchError(buildResult: 'UNSTABLE', stageResult: 'FAILURE') {
                    withCredentials([string(credentialsId: "elliott-codecov-token", variable: "CODECOV_TOKEN")]) {
                        sh "codecov --token ${env.CODECOV_TOKEN}"
                    }
                }
            }
        }
    }
}
