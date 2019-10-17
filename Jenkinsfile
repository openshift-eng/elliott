@Library('art-ci-toolkit@master') _

pipeline {
    agent {
        docker {
            image "redhat/art-ci-toolkit:latest"
            alwaysPull true
            args "--entrypoint=''"
        }
    }
    stages {
        stage("Tests & Coverage") {
            steps {
                script {
                    catchError(stageResult: 'FAILURE') {
                        sh "tox > results.txt 2>&1"
                    }
                    results = readFile("results.txt").trim()
                    echo results
                    if (env.CHANGE_ID) {
                        commentOnPullRequest(msg: "### Build <span>#</span>${env.BUILD_NUMBER}\n```\n${results}\n```")
                    }
                }
            }
        }
        stage("Publish Coverage Report") {
            steps {
                catchError(buildResult: 'UNSTABLE', stageResult: 'FAILURE') {
                    withCredentials([string(credentialsId: "elliott-codecov-token", variable: "CODECOV_TOKEN")]) {
                        sh "codecov --token ${env.CODECOV_TOKEN}"
                    }
                }
            }
        }
        stage("Publish to PyPI") {
            when {
                buildingTag()
            }
            steps {
                sh "python3 setup.py bdist_wheel --universal"
                sh "python3 -m twine check dist/*"
                script { publishToPyPI() }
            }
        }
    }
}
